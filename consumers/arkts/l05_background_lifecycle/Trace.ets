import { hilog } from '@kit.PerformanceAnalysisKit';
import { PROBE_NONCE } from './ProbeConfig';
export function emit(label: string, values: number[]): void {
  hilog.info(0x0000, 'MadBL05Background', 'L05_BACKGROUND_CASE %{public}s %{public}s %{public}s', PROBE_NONCE, label, JSON.stringify(values));
}
export function failed(error: Error): void {
  hilog.error(0x0000, 'MadBL05Background', 'L05_BACKGROUND_FAILED %{public}s %{public}s', PROBE_NONCE, error.message);
}
export function complete(): void {
  hilog.info(0x0000, 'MadBL05Background', 'L05_BACKGROUND_COMPLETE %{public}s', PROBE_NONCE);
}
