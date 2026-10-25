import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { PROBE_NONCE } from './ProbeConfig';
export default class EntryAbility extends UIAbility {
  onCreate(): void { hilog.info(0x0000, 'MadBC07Probe', 'PROBE_STARTED %{public}s', PROBE_NONCE); }
  onWindowStageCreate(stage: window.WindowStage): void { stage.loadContent('pages/Index', (error) => {
    if (error.code) { hilog.error(0x0000, 'MadBC07Probe', 'PROBE_FAILED %{public}s %{public}s', PROBE_NONCE, error.message); }
    else { hilog.info(0x0000, 'MadBC07Probe', 'PROBE_FINISHED %{public}s', PROBE_NONCE); }
  }); }
}
