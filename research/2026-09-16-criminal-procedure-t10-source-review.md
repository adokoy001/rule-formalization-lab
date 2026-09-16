# T10 刑事訴訟法203条→205条の公式原文確認と限定モデル方針

作成: 2026-09-16

## 結論

T10の最初の実法令packは、刑事訴訟法203条により司法警察員から送致された被疑者を検察官が受け取る経路に限定する。標準の数値期限を次の3本に分けて診断し、手続全体の適法・違法は判定しない。

- 203条: 身体拘束時から送致手続まで48時間。
- 205条1項: 検察官の受領時から、勾留請求又は公訴提起まで24時間。
- 205条2項: 身体拘束時から、同じ勾留請求又は公訴提起まで72時間。

205条の2期限は別々に保存・表示する。一方だけを早い期限へ畳まず、送致手続と検察官の受領も別eventにする。206条の「やむを得ない事情」、疎明、裁判官の認定は機械的に確定せず、数値超過を自動で期限内へ書き換えない。

## 固定した公式版

2026-09-16にe-Gov法令API v2の現行施行版を照合した。

| 項目 | 固定値 |
|---|---|
| Law ID | `323AC0000000131` |
| 法令名 | 刑事訴訟法（昭和二十三年法律第百三十一号） |
| revision ID | `323AC0000000131_20260813_508AC0000000067` |
| 施行日 | `2026-08-13` |
| XML SHA-256 | `76701aca5313dbd6c021c33dfc922c039e3a9f5e9843e7df256dfd8e6bedaa22` |
| metadata SHA-256 | `8a7d6a7f2fafa69f206d95651a819cfb06522e7d0d5698db3ea9249e1370c387` |

公式URL:

- [e-Gov法令検索・固定版](https://laws.e-gov.go.jp/law/323AC0000000131/20260813_508AC0000000067)
- [e-Gov法令API v2・XML](https://laws.e-gov.go.jp/api/2/law_file/xml/323AC0000000131_20260813_508AC0000000067)
- [e-Gov法令API v2・metadata](https://laws.e-gov.go.jp/api/2/law_data/323AC0000000131_20260813_508AC0000000067)

[保存したsource package](../examples/sources/criminal-procedure-55-203-206/)は55条・203条・204条・205条・206条をArticle単位で抽出した。204条は最初の意味モデルでは使わないが、206条の「前三条」が203〜205条を指すため、参照先として保存した。

| package anchor | SHA-256 |
|---|---|
| source spec | `6a88b87e17c37a7df312336ed2fa72d159ced7bad1a138ff26c3a18324008ef0` |
| source unit manifest | `74f57298be484950f31b89dacfb81908f637b02ab2eb8b8d14e43a618bf1a7a8` |
| bundle | `6c8510b9c9022c6d4974bd1cc00fffdcd85b1ca4547f1027c644b68c5dc9a7fe` |

外部bundle hashを指定したoffline checkerは`VERIFIED`、source unit 5、未解決reference 5を返した。

```bash
python3 -m rulekernel verify-source \
  examples/sources/criminal-procedure-55-203-206/source-spec.json \
  examples/sources/criminal-procedure-55-203-206/bundle \
  --expected-bundle-sha256 6c8510b9c9022c6d4974bd1cc00fffdcd85b1ca4547f1027c644b68c5dc9a7fe \
  --json
```

## 関連する公式規則と未解決の延長

最高裁判所が公開する[刑事訴訟規則（2026年5月21日版）](https://www.courts.go.jp/assets/keijisosyoukisoku_20260521.pdf)も確認した。規則148条1項1号は、逮捕、引致、送致の手続、送致を受けた各年月日時を別々に記録させる。この記録項目は、T10で`send_procedure`と`prosecutor_receipt`を別eventにする根拠を補強する。規則148条2項は、法定時間を守れなかったときに、やむを得ない事情を認める資料も提供させる。したがって、事情の主張だけを206条による自動延長として実装しない。

一方、刑事訴訟法56条と刑事訴訟規則66条・66条の2には、場所、距離又は交通通信に関係する期間延長の規定がある。203条から205条の今回の経路へどう適用されるかは、この限定packでは確定しない。fixtureは延長決定を入力せず、一般的な適用可能性を`unresolved`として残す。

## 将来版によるstale条件

e-Govにはrevision `323AC0000000131_20270331_507AC0000000039`も公開されているが、2026-09-16時点では`UnEnforced`である。この版は205条へ新しい2項を挿入し、現在の2項から4項を3項から5項へ移す。施行された時点で、現行revisionへ結び付けたT10 packをstaleとして扱い、source、coverage、review、model bindingを作り直す。将来版の内容を現在施行中の規則へ先取りしない。

## source unitごとの採用範囲

| 条文 | coverage | T10で採用する部分 | 残す境界 |
|---|---|---|---|
| 55条 | `partial` | 時で計算する期間を即時から起算する部分 | 日・月・年、休日、暦、時効は未対応 |
| 203条 | `partial` | 1項の48時間と、5項の期限内に送致手続をしない場合の釈放 | 留置の必要性、告知、弁解、弁護人関係、「直ちに」の数値化は未対応 |
| 204条 | `out_of_scope` | 206条の参照先としてのみ保存 | 検察官自身の逮捕経路は別pack |
| 205条 | `partial` | 1項の受領後24時間、2項の拘束後72時間、3項の公訴提起、4項の釈放 | 留置の必要性、「直ちに」の数値化、手続全体の法的評価は未対応 |
| 206条 | `unresolved` | 数値超過時に評価未確定であることを表示 | やむを得ない事情、疎明、裁判官の認定を自動判定しない |

このcoverageは開発fixture作者による`manual_fixture_review`であり、法律専門家の承認ではない。原文との意味対応は`provisional: true`として扱う。

## 有限時間モデルへの写し方

- 単位は`hour`、座標は整数`tick`と同一tick内の`phase`の組とする。暗黙の日・暦変換はしない。
- 観測終了は排他的cutとし、event座標が観測終了より小さいときだけ観測済みとする。
- 期限上端は包含する。eventがdueと同じ座標なら期限内。
- eventがなく観測終了がdue以下ならnative statusは`pending`、観測終了がdueより後なら`violated_missing`。期限後にeventがあれば`violated_late`。
- 203条の`send_procedure`と205条の`prosecutor_receipt`を別eventにする。
- 205条は`detention_request`又は`public_prosecution`のどちらかを対象eventとし、受領+24と拘束+72の両方を独立に評価する。
- 203条の48時間normが`violated_late`又は`violated_missing`なら、選択した203条5項に基づく`SELECTED_TEXT_RELEASE_TRIGGERED`を別出力にする。205条は24時間norm又は72時間normの一方以上が同じ状態なら、選択した205条4項に基づいて同診断を出す。ただし「直ちに」の時刻や実際の釈放完了は判定しない。
- 206条に関係する事情が入力にあっても、標準期限の結果を期限内へ変更しない。`ARTICLE_206_ASSESSMENT_UNRESOLVED`を併記する。

実装が出力する各normのnative statusは、期限内eventの`satisfied`、期限後eventの`violated_late`、期限後までeventがない`violated_missing`、観測未完了の`pending`である。調査段階の用語では順に`NUMERIC_WITHIN`、`NUMERIC_EXCEEDED / LATE_EVENT`、`NUMERIC_EXCEEDED / NO_EVENT_AFTER_DEADLINE`、`OBSERVATION_INCOMPLETE`へ対応する。大文字名は概念上の対応表であり、現在のJSON field値ではない。`LEGAL`、`ILLEGAL`、手続全体の`COMPLIANT`は出力しない。

## 固定する境界例

| 拘束 | 送致 | 受領 | 勾留請求又は公訴 | 観測終了 | 期待 |
|---:|---:|---:|---:|---:|---|
| 0 | 48 | - | - | 49 | 203条48時間の一致は期限内 |
| 0 | 49 | - | - | 50 | 203条の数値超過 |
| 0 | 47 | 48 | 72 | 73 | 3本とも期限内 |
| 0 | 47 | 40 | 65 | 66 | 受領+24だけ超過、拘束+72は期限内 |
| 0 | 47 | 49 | 73 | 74 | 受領+24は期限内、拘束+72だけ超過 |
| 0 | 47 | 48 | 公訴72 | 73 | 勾留請求がなくても2期限を満たす |
| 0 | 47 | 48 | なし | 72 | 期限座標までの排他的観測なので未完了 |
| 0 | 47 | 48 | なし | 73 | 2期限とも数値超過、釈放trigger表示 |
| 0 | 47 | 48 | 73 | 74 | 数値超過と206条評価未確定を併記 |

負例では、送致時刻を受領時刻として使う変異、205条の2期限の片方を削る変異、206条の事情入力だけで自動延長する変異、source unit・quote・review・model hashの改ざんを拒否する。

## この調査で保証しないこと

- 203条→205条経路以外、特に204条経路の診断。
- 身体拘束開始、送致手続、受領、勾留請求、公訴提起という事実の認定。
- 「留置の必要」「直ちに」「やむを得ない事情」「正当」の評価。
- 55条全体の暦計算、56条・規則66条・66条の2の延長の適用判断、その他の条文・規則、判例、個別事件への適用。
- 数値期限診断から手続全体の適法・違法、証拠能力、救済を導くこと。
