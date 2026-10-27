import { Snapshot } from './Boundary';
export function check(condition: boolean, label: string): void {
  if (!condition) { throw new Error('L05_BACKGROUND_ASSERT:' + label); }
}
export function snapshot(actual: Snapshot | undefined, value: number, text: string, label: string): void {
  check(actual !== undefined, label + ':missing');
  if (actual !== undefined) { check(actual.value === value && actual.text === text, label + ':value'); }
}
export async function until(test: () => boolean, label: string): Promise<void> {
  const deadline: number = Date.now() + 10000;
  while (!test()) {
    check(Date.now() < deadline, label + ':timeout');
    await new Promise<void>((resolve) => { setTimeout(resolve, 5); });
  }
}
