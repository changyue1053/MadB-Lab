#!/usr/bin/env bash
# 鸿蒙调试签名材料的函数库：被 source 后提供 ohos_sign_material；本身不设 set -e，也不执行任何命令。
# Public SDK community debug recipe; HAP is signed by Hvigor. No user private signing material is read.
# Only prepares:
# 证书链、调试 profile，以及 hvigor 认的 signingConfigs 一项（口令按 hvigor 的格式加密），不做 sign-app 外签。
# 调用前须定义 SIGN_LIB（DevEco SDK 的 toolchains/lib）、JAVA_BIN（DevEco 自带 JBR 的 bin）、
# NODE（DevEco 自带的 node）与 DECIPHER（DevEco 自带 hvigor 的 decipher-util.js）。写法保持 bash 3.2 兼容。
#
# 只用 SDK 自带的 OpenHarmony 社区调试证书链，不需要华为账号；签出的是调试形态的 HAP，不能用于发布。
# 口令 123456 是 SDK 自带 OpenHarmony.p12 的公开开发口令。

# ohos_sign_material <签名工作目录> <bundleName> [udid]
#   1. 从 SDK 密钥库导出二级 CA（subca.cer）与根 CA（rootca.cer）证书
#   2. generate-app-cert 生成应用证书链 app-release-chain.cer（密钥别名 "openharmony application release"）
#   3. 以 SDK 的调试 profile 模板为底，填入 bundle 名、应用证书与设备列表（udid 为空则不绑定设备），有效期 3650 天，sign-profile 签好
#   4. 密钥库复制进工作目录，写 hvigor 的解密材料（material/）与 signing.json（app/ohos/hvigorfile.ts 在构建时把它注入 signingConfigs）
#   全部写进 <签名工作目录>（调用方传仓根下的 .local/ohos-sign），不入库。第 2、3、4 步失败打 [err] 并返回 1，成功返回 0。
ohos_sign_material() {
    local sign_dir="$1" bundle="$2" udid="${3:-}"
    local kt="${JAVA_BIN}/keytool" java="${JAVA_BIN}/java"
    mkdir -p "${sign_dir}"
    # 1. 导出证书链的两级 CA
    "${kt}" -exportcert -rfc -keystore "${SIGN_LIB}/OpenHarmony.p12" -storepass 123456 \
        -alias "openharmony application ca" -file "${sign_dir}/subca.cer" >/dev/null 2>&1
    "${kt}" -exportcert -rfc -keystore "${SIGN_LIB}/OpenHarmony.p12" -storepass 123456 \
        -alias "openharmony application root ca" -file "${sign_dir}/rootca.cer" >/dev/null 2>&1
    # 2. 由二级 CA 签发应用证书，输出完整证书链
    if ! "${java}" -jar "${SIGN_LIB}/hap-sign-tool.jar" generate-app-cert \
            -keyAlias "openharmony application release" -signAlg SHA256withECDSA \
            -issuer "C=CN,O=OpenHarmony,OU=OpenHarmony Team,CN=OpenHarmony Application CA" \
            -issuerKeyAlias "openharmony application ca" \
            -subject "C=CN,O=OpenHarmony,OU=OpenHarmony Team,CN=OpenHarmony Application Release" \
            -keystoreFile "${SIGN_LIB}/OpenHarmony.p12" \
            -subCaCertFile "${sign_dir}/subca.cer" -rootCaCertFile "${sign_dir}/rootca.cer" \
            -outForm certChain -outFile "${sign_dir}/app-release-chain.cer" \
            -keyPwd 123456 -keystorePwd 123456 -issuerKeyPwd 123456 -validity 3650 >/dev/null 2>&1; then
        echo "[err] generate-app-cert 失败"; return 1
    fi
    # 3. 生成调试 profile（模板文件名 Unsgned… 是 SDK 原样拼写），再用 SDK 的调试 profile 证书签它
    "${MADB_LAB_PYTHON:?explicit Lab Python required}" - "${SIGN_LIB}" "${sign_dir}" "${bundle}" "${udid}" <<'PYEOF'
import json, re, sys, time
lib, sign, bundle, udid = sys.argv[1:5]
prof = json.load(open(f"{lib}/UnsgnedDebugProfileTemplate.json"))
chain = open(f"{sign}/app-release-chain.cer").read()
# 证书链里的第一张就是应用证书本身
leaf = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\n", chain, re.S).group(0)
prof["bundle-info"]["bundle-name"] = bundle
prof["bundle-info"]["development-certificate"] = leaf
prof["debug-info"]["device-ids"] = [udid] if udid else []
now = int(time.time())
# 生效时间往前推一天，到期时间是 3650 天后
prof["validity"] = {"not-before": now - 86400, "not-after": now + 86400 * 3650}
json.dump(prof, open(f"{sign}/mad-debug-profile.json", "w"), indent=2, ensure_ascii=False)
PYEOF
    if ! "${java}" -jar "${SIGN_LIB}/hap-sign-tool.jar" sign-profile \
            -keyAlias "openharmony application profile debug" -signAlg SHA256withECDSA -mode localSign \
            -profileCertFile "${SIGN_LIB}/OpenHarmonyProfileDebug.pem" -inFile "${sign_dir}/mad-debug-profile.json" \
            -keystoreFile "${SIGN_LIB}/OpenHarmony.p12" -outFile "${sign_dir}/mad-debug-profile.p7b" \
            -keyPwd 123456 -keystorePwd 123456 >/dev/null 2>&1; then
        echo "[err] sign-profile 失败"; return 1
    fi
    # 4. hvigor 的 signingConfigs 不收明文口令：按它 DecipherUtil 的格式加密（解密材料目录必须与密钥库同目录，所以复制一份密钥库）
    cp "${SIGN_LIB}/OpenHarmony.p12" "${sign_dir}/OpenHarmony.p12"
    if ! MAD_SIGN_PASSWORD=123456 "${NODE}" - "${sign_dir}" "${DECIPHER}" <<'JSEOF'
// hvigor 的解法：三段分量与内置分量逐字节异或、加盐 PBKDF2 得根密钥；根密钥解出工作密钥，工作密钥解出口令。
// 密文：4 字节大端长度（密文 + 认证标签）| 12 字节 IV | 密文 | 16 字节 AES-128-GCM 标签。分量与密钥每次新生成
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const [signDir, decipherJs] = process.argv.slice(2);
const builtIn = JSON.parse(fs.readFileSync(decipherJs, 'utf8').match(/DecipherUtil\.component=new Int8Array\((\[[-0-9,]+\])\)/)[1]);
const material = path.join(signDir, 'material');
fs.rmSync(material, { recursive: true, force: true });
const put = (dir, bytes) => { fs.mkdirSync(path.join(material, dir), { recursive: true }); fs.writeFileSync(path.join(material, dir, 'value'), bytes, { mode: 0o600 }); };
const encrypt = (key, plain) => {
  const iv = crypto.randomBytes(12), cipher = crypto.createCipheriv('aes-128-gcm', key, iv);
  const body = Buffer.concat([cipher.update(plain), cipher.final()]), size = Buffer.alloc(4);
  size.writeUInt32BE(body.length + 16);
  return Buffer.concat([size, iv, body, cipher.getAuthTag()]);
};
const parts = [0, 1, 2].map(() => crypto.randomBytes(16)), salt = crypto.randomBytes(16);
parts.forEach((part, index) => put(`fd/${index}`, part));
put('ac', salt);
const mix = Buffer.alloc(16);
for (let i = 0; i < 16; i++) mix[i] = parts[0][i] ^ parts[1][i] ^ parts[2][i] ^ builtIn[i];
// 与 hvigor 一致：异或结果先转成字符串再进 PBKDF2
const rootKey = crypto.pbkdf2Sync(mix.toString(), salt, 10000, 16, 'sha256'), workKey = crypto.randomBytes(16);
put('ce', encrypt(rootKey, workKey));
const secret = encrypt(workKey, Buffer.from(process.env.MAD_SIGN_PASSWORD)).toString('hex');
const config = { name: 'mad-debug', type: 'HarmonyOS', material: {
  storeFile: path.join(signDir, 'OpenHarmony.p12'), storePassword: secret, keyAlias: 'openharmony application release',
  keyPassword: secret, signAlg: 'SHA256withECDSA', profile: path.join(signDir, 'mad-debug-profile.p7b'),
  certpath: path.join(signDir, 'app-release-chain.cer') } };
fs.writeFileSync(path.join(signDir, 'signing.json'), JSON.stringify(config, null, 2) + '\n', { mode: 0o600 });
JSEOF
    then
        echo "[err] hvigor 签名配置生成失败"; return 1
    fi
    return 0
}
