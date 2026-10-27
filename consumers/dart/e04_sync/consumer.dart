// Independent ADR-0026 ordinary consumer. No raw binding or producer imports.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';
import 'dart:typed_data';

import 'package:madb_dart_ffi/madb_dart_ffi.dart';

class LabAssertion implements Exception {
  LabAssertion(this.message);
  final String message;
  @override
  String toString() => message;
}

void require(bool condition, String description) {
  if (!condition) throw LabAssertion(description);
}

String expectRange(void Function() operation) {
  try {
    operation();
  } on RangeError {
    return 'RangeError';
  }
  throw LabAssertion('expected RangeError');
}

String expectState(void Function() operation) {
  try {
    operation();
  } on StateError {
    return 'StateError';
  }
  throw LabAssertion('expected StateError');
}

bool equalBytes(List<int> left, List<int> right) {
  if (left.length != right.length) return false;
  for (var i = 0; i < left.length; i++) {
    if (left[i] != right[i]) return false;
  }
  return true;
}

void closeRemaining(Engine engine) {
  if (engine.state != EngineState.closed) engine.close();
}

List<Map<String, Object?>> values(String directory) {
  final api = MadbLibrary.open(directory);
  final engine = api.createEngine();
  final rows = <Map<String, Object?>>[];
  try {
    require(engine.state == EngineState.open, 'new engine must be open');
    final vectors = <(String, Uint8List, int)>[
      ('empty', Uint8List(0), 0),
      ('zero', Uint8List.fromList([0]), 0),
      ('byte-max', Uint8List.fromList([255]), 255),
      ('mixed', Uint8List.fromList([0, 1, 127, 128, 255]), 511),
      ('max-length', Uint8List.fromList(List.filled(65536, 255)), 16711680),
    ];
    for (final (id, input, expected) in vectors) {
      final before = Uint8List.fromList(input);
      final sum = engine.checksum(input);
      final preserved = equalBytes(before, input);
      require(sum == expected && preserved, 'checksum vector $id');
      rows.add({
        'id': id,
        'length': input.length,
        'sum': sum,
        'input_preserved': preserved,
        'state': engine.state.name,
      });
    }
  } finally {
    closeRemaining(engine);
  }
  rows.add({'id': 'explicit-close', 'state': engine.state.name});
  // Sequential reopening is part of this fixed package, not version coexistence.
  final second = MadbLibrary.open(directory).createEngine();
  try {
    final sum = second.checksum(Uint8List.fromList([255, 1]));
    require(sum == 256, 'sequential reopen value');
    rows.add({
      'id': 'sequential-reopen',
      'sum': sum,
      'state': second.state.name,
    });
  } finally {
    closeRemaining(second);
  }
  rows.add({'id': 'second-close', 'state': second.state.name});
  return rows;
}

List<Map<String, Object?>> ranges(String directory) {
  final engine = MadbLibrary.open(directory).createEngine();
  final rows = <Map<String, Object?>>[];
  try {
    final long = Uint8List.fromList(List.filled(65537, 7));
    final before = Uint8List.fromList(long);
    final error = expectRange(() {
      engine.checksum(long);
    });
    rows.add({
      'id': 'too-long',
      'error': error,
      'state': engine.state.name,
      'input_preserved': equalBytes(before, long),
    });
    for (final timeout in [-1, 4294967296]) {
      final error = expectRange(() {
        engine.close(timeoutMilliseconds: timeout);
      });
      rows.add({
        'id': 'timeout-$timeout',
        'error': error,
        'state': engine.state.name,
      });
    }
    require(
      engine.state == EngineState.open,
      'parameter rejection retains open owner',
    );
    final sum = engine.checksum(Uint8List.fromList([2, 3]));
    require(sum == 5, 'owner remains usable after parameter rejection');
    rows.add({'id': 'after-rejection', 'sum': sum, 'state': engine.state.name});
  } finally {
    closeRemaining(engine);
  }
  rows.add({'id': 'explicit-close', 'state': engine.state.name});
  return rows;
}

List<Map<String, Object?>> close(String directory) {
  final api = MadbLibrary.open(directory);
  final rows = <Map<String, Object?>>[];
  // A zero waiting budget need not complete asynchronous native shutdown.
  // These successful closes do not assert a timeout-interleaving guarantee.
  for (final timeout in [1000, 4294967295]) {
    final engine = api.createEngine();
    try {
      rows.add({'id': 'before-$timeout', 'state': engine.state.name});
      engine.close(timeoutMilliseconds: timeout);
      rows.add({'id': 'closed-$timeout', 'state': engine.state.name});
      engine.close();
      rows.add({'id': 'repeat-$timeout', 'state': engine.state.name});
      final error = expectState(() {
        engine.checksum(Uint8List(0));
      });
      rows.add({
        'id': 'after-$timeout',
        'error': error,
        'state': engine.state.name,
      });
    } finally {
      closeRemaining(engine);
    }
  }
  return rows;
}

void receiver(SendPort ready) {
  final input = ReceivePort();
  ready.send(input.sendPort);
  input.listen((Object? message) {
    if (message == 'stop') input.close();
  });
}

Future<List<Map<String, Object?>>> isolate(String directory) async {
  final api = MadbLibrary.open(directory);
  final engine = api.createEngine();
  final ready = ReceivePort();
  final exited = ReceivePort();
  final errors = ReceivePort();
  final errorMessages = <Object?>[];
  final subscription = errors.listen(errorMessages.add);
  Isolate? worker;
  SendPort? channel;
  var exitConfirmed = false;
  final rows = <Map<String, Object?>>[];
  try {
    worker = await Isolate.spawn(
      receiver,
      ready.sendPort,
      onExit: exited.sendPort,
      onError: errors.sendPort,
      errorsAreFatal: true,
    );
    channel =
        await ready.first.timeout(const Duration(seconds: 10)) as SendPort;
    for (final (id, owner) in <(String, Object)>[
      ('library', api),
      ('engine', engine),
    ]) {
      var rejected = false;
      try {
        channel.send(owner);
      } on ArgumentError {
        rejected = true;
      }
      require(rejected, '$id must reject isolate transfer');
      rows.add({'id': id, 'error': 'ArgumentError'});
    }
    final sum = engine.checksum(Uint8List.fromList([11, 12]));
    require(sum == 23, 'original isolate owner still usable');
    rows.add({'id': 'original-owner', 'sum': sum, 'state': engine.state.name});
    engine.close();
    rows.add({'id': 'explicit-close', 'state': engine.state.name});
    channel.send('stop');
    await exited.first.timeout(const Duration(seconds: 10));
    exitConfirmed = true;
    require(errorMessages.isEmpty, 'receiving isolate reported an error');
    rows.add({
      'id': 'receiver-exit',
      'normal': true,
      'errors': errorMessages.length,
    });
  } finally {
    // A kill only bounds failed tests; it never emits receiver-exit success.
    if (!exitConfirmed) worker?.kill(priority: Isolate.immediate);
    ready.close();
    exited.close();
    errors.close();
    await subscription.cancel();
    closeRemaining(engine);
  }
  return rows;
}

List<Map<String, Object?>> load(String directory, String expected) {
  try {
    final api = MadbLibrary.open(directory);
    if (expected != 'success')
      throw LabAssertion('damaged package unexpectedly opened');
    final engine = api.createEngine();
    try {
      final sum = engine.checksum(Uint8List.fromList([1, 2]));
      require(sum == 3, 'loaded package ordinary call');
      return [
        {'id': 'load', 'kind': 'success', 'sum': sum},
      ];
    } finally {
      closeRemaining(engine);
    }
  } on MadbLoadException catch (error) {
    require(
      error.kind == expected,
      'load kind ${error.kind}, expected $expected',
    );
    return [
      {
        'id': 'load',
        'kind': error.kind,
        'path': error.path,
        'expected_digest': error.expectedDigest,
        'actual_digest': error.actualDigest,
      },
    ];
  }
}

Future<void> main(List<String> arguments) async {
  try {
    require(arguments.length >= 2, 'usage: case native-directory [load-kind]');
    final mode = arguments[0];
    final directory = arguments[1];
    final List<Map<String, Object?>> observations;
    switch (mode) {
      case 'values':
        observations = values(directory);
      case 'ranges':
        observations = ranges(directory);
      case 'close':
        observations = close(directory);
      case 'isolate':
        observations = await isolate(directory);
      case 'load':
        require(arguments.length == 3, 'load requires exact expected kind');
        observations = load(directory, arguments[2]);
      default:
        throw LabAssertion('unknown case $mode');
    }
    stdout.writeln(
      jsonEncode({'case': mode, 'pid': pid, 'observations': observations}),
    );
  } on LabAssertion catch (error) {
    stderr.writeln('E04 assertion: $error');
    exitCode = 2;
  } catch (error, stack) {
    stderr.writeln('E04 unexpected: $error\n$stack');
    exitCode = 3;
  }
}
