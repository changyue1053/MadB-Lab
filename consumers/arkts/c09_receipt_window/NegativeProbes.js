// These deliberate type-boundary violations test the public helper's runtime gate.
let reads = 0;
let codeReads = 0;
let prototypeReads = 0;
let originalGetterError;
export function invalidProbe() { return null; }
export function nonvoidProbe(kind, entered) {
  return () => {
    entered();
    if (kind === 'callback-promise') return Promise.resolve();
    return {get then() { reads++; throw new Error('LAB_THEN_MUST_NOT_BE_READ'); }};
  };
}
export function thenReads() { return reads; }
export function throwCodeGetterError() {
  originalGetterError = new Error('InjectedReceiptGetter');
  Object.defineProperty(originalGetterError, 'code', {get() {
    codeReads++;
    throw new Error('LAB_CODE_GETTER_MUST_NOT_BE_READ');
  }});
  throw originalGetterError;
}
export function isCodeGetterError(error) { return error === originalGetterError; }
export function throwNonError(kind) {
  if (kind === 'callback-throw-undefined') throw undefined;
  if (kind !== 'callback-throw-proxy') throw new Error('LAB_UNKNOWN_THROW_FIXTURE');
  throw new Proxy({}, {getPrototypeOf() {
    prototypeReads++;
    throw new Error('LAB_THROWN_PROXY_PROTOTYPE_TRAP');
  }});
}
export function propertyReads() { return [reads, codeReads, prototypeReads]; }
