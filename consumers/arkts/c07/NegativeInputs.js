// Independent JavaScript seam for inputs ArkTS cannot legally construct.
// Calls only the supplied ordinary public method; imports no native/provider code.
function check(value, name) {
  if (!value) throw new Error('LAB_ASSERT:' + name);
}

export function runNegativeInputs(roundtrip, isBoundaryError) {
  let invalid = 0;
  const values = [true, '1', null, NaN, Infinity, -Infinity, 0.25, 2147483648, -2147483649];
  const texts = [null, 42, '\ud800', '\udc00', 'a'.repeat(1025), '中'.repeat(342), '😀'.repeat(256) + 'a'];
  function reject(input) {
    let observed;
    try { roundtrip(input); } catch (error) { observed = error; }
    check(observed instanceof Error && observed.code === 'InvalidArgument', 'invalid-argument');
    check(isBoundaryError(observed), 'invalid-argument-public-error-type');
    invalid++;
  }
  for (const value of values) reject({ value, text: 'bad-value' });
  for (const text of texts) reject({ value: 1, text });

  let valueReads = 0, textReads = 0;
  const copied = roundtrip({
    get value() { valueReads++; return 41; },
    get text() { textReads++; return 'getter'; }
  });
  check(copied.value === 41 && copied.text === 'getter', 'getter-result');
  let preserved = 0;
  for (const field of ['value', 'text']) {
    const original = new Error('LAB_GETTER_' + field);
    let laterReads = 0;
    const input = field === 'value'
      ? { get value() { throw original; }, get text() { laterReads++; return 'unread'; } }
      : { get value() { return 2; }, get text() { throw original; } };
    let observed;
    try { roundtrip(input); } catch (error) { observed = error; }
    check(observed === original && laterReads === 0, 'getter-original-identity');
    const recovery = roundtrip({ value: 3, text: 'recovered\u0000' });
    check(recovery.value === 3 && recovery.text === 'recovered\u0000', 'getter-recovery');
    preserved++;
  }

  const names = ['value', 'text'];
  const previous = names.map(name => Object.getOwnPropertyDescriptor(Object.prototype, name));
  const marker = new Error('LAB_INHERITED_SETTER');
  let setterHits = 0, positiveHits = 0, ownFields = 0;
  try {
    for (const name of names) {
      const descriptor = Object.create(null);
      descriptor.configurable = true;
      descriptor.set = function () { setterHits++; throw marker; };
      Object.defineProperty(Object.prototype, name, descriptor);
    }
    let caught;
    try { const ordinary = {}; ordinary.value = 7; } catch (error) { caught = error; }
    check(caught === marker && setterHits === 1, 'setter-positive-control');
    positiveHits = setterHits;
    setterHits = 0;
    const output = roundtrip({ value: 7, text: 'own-data\u0000' });
    check(output.value === 7 && output.text === 'own-data\u0000', 'own-data-values');
    for (const name of names) {
      const descriptor = Object.getOwnPropertyDescriptor(output, name);
      check(descriptor && Object.prototype.hasOwnProperty.call(descriptor, 'value') &&
        descriptor.get === undefined && descriptor.set === undefined, 'own-data-property');
      ownFields++;
    }
  } finally {
    for (let i = 0; i < names.length; i++) {
      if (previous[i] === undefined) delete Object.prototype[names[i]];
      else Object.defineProperty(Object.prototype, names[i], previous[i]);
    }
  }
  return [invalid, valueReads, textReads, preserved, positiveHits, setterHits, ownFields];
}

export function runClosingGetter(roundtrip, requestClose) {
  let valueReads = 0, textReads = 0, observed;
  try {
    roundtrip({
      get value() { valueReads++; requestClose(); return 5; },
      get text() { textReads++; return 'closed-during-getter'; }
    });
  } catch (error) { observed = error; }
  check(observed instanceof Error && observed.code === 'Closing', 'getter-close-recheck');
  check(valueReads === 1 && textReads <= 1, 'getter-close-single-read');
}
