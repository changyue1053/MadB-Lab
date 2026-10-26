// Lab-owned JS seam for values ArkTS cannot construct as synchronous void inputs.
// It imports no private SDK or native code and receives only public closures.
export function invalidProbe(): () => void;
export function nonvoidProbe(kind: string, entered: () => void): () => void;
export function thenReads(): number;
export function throwCodeGetterError(): void;
export function isCodeGetterError(error: Error): boolean;
export function throwNonError(kind: string): void;
export function propertyReads(): number[];
