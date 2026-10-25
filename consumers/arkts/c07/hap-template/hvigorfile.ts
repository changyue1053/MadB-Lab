import { appTasks, OhosAppContext, OhosPluginId } from '@ohos/hvigor-ohos-plugin';
import { HvigorNode, HvigorPlugin } from '@ohos/hvigor';
import * as fs from 'fs';
import * as path from 'path';

function probeSigning(): HvigorPlugin {
  return {
    pluginId: 'com.madb.c07probe.signing',
    apply(node: HvigorNode) {
      node.afterNodeEvaluate(() => {
        const file = process.env.MADB_SIGN_CONFIG || path.resolve(node.getNodeDir().getPath(), '.signing/signing.json');
        const signing = JSON.parse(fs.readFileSync(file, 'utf8'));
        const context = node.getContext(OhosPluginId.OHOS_APP_PLUGIN) as OhosAppContext;
        const profile = context.getBuildProfileOpt();
        profile.app.signingConfigs = [signing];
        profile.app.products.forEach(product => product.signingConfig = signing.name);
        context.setBuildProfileOpt(profile);
      });
    },
  };
}
export default { system: appTasks, plugins: [probeSigning()] };
