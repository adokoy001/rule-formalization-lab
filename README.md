# Rule Formalization Lab

完全に趣味として、現実的な範囲のルールを検証し、穴や不整合に気づきやすくする支援ツール。

作成: 2026-09-14 / 更新: 2026-09-16

> **用途上の注意:** 趣味・研究用の検証支援プロジェクトであり、法律相談や現実の法的判断を提供しない。結果は、明示した有限モデル、原文版、解釈、仮定の範囲に限られる。

第三者由来データとライセンスの状態は[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を参照。

**自前検証カーネル v0.1、原文package v0.1、手書き解釈IR v0.1、段階別到達可能性診断 v0.1に加え、T08の有限規範検証カーネル v0.1が動く。T06固定合成ベンチマーク、T07刑法41条の限定的手書き解釈pack、T08架空規範fixtureを保存した。** 手書きの有限モデルを全列挙し、結論の衝突、必要な結論が出ない条件、改定差分、規則の発火・抑止範囲を調べる。形式化前の原文はraw bytes、版、抽出文、構造位置を固定し、非信頼の解釈候補、ホスト管理のreview・scope期待、既存Coreへの決定的変換を別々の入力として保存できる。段階別診断ではguard、facts、constraints、override後の件数と最初のwitnessを分け、外部hash付きscope期待と照合する。各経路のproducerとは別のcheckerが証拠やCore・来歴をoffline再構成する。Python標準ライブラリだけを使い、既成ソルバー・APIキー・追加インストールは不要。保存済みモデル・原文・解釈packageの再検査はnetwork不要で、e-Govから新しく取得するコマンドだけがnetworkを使う。

## 試す

WSL Ubuntuのターミナルで、次を実行する。Python 3.11以上を想定し、現在の環境のPython 3.14.4で検証した。

```bash
git clone https://github.com/adokoy001/rule-formalization-lab.git
cd rule-formalization-lab
python3 -m rulekernel check examples/club-broken.json
python3 -m rulekernel check examples/club-fixed.json
python3 -m rulekernel check examples/club20/broken.json
python3 -m rulekernel check examples/club20/fixed.json
python3 -m normkernel verify examples/norms/t08-three-way/model.json \
  examples/norms/t08-three-way/certificate.json \
  --expected-certificate-sha256 a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a
```

PowerShellから、WSLのhomeにcloneしたリポジトリを1行で試す場合:

```powershell
wsl.exe -d Ubuntu --exec bash -lc "cd ~/rule-formalization-lab && python3 -m rulekernel check examples/club-broken.json"
```

[6条の架空規約](examples/README.md)を、0〜25歳 × 学生か否か = 52状況で検査する。

| 検査結果 | 問題のある版 | 境界を揃えた版 |
|---|---:|---:|
| 会員資格の衝突 | 4状況（18・19歳） | 0 |
| 料金の扱いの抜け | 4状況（18・19歳） | 0 |

衝突には具体的な入力・結論・関係する条文IDと原文を表示する。ここでの件数は対象者数ではなく、学生区分も含む入力の組合せの数。

20規則版では416状況を検査し、問題版で資格衝突32・料金gap32・貸出衝突4、修正版で全11照会0となる。原文、手書きの期待表、具体例は[20規則教材](examples/club20/README.md)にある。

終了コードは **0: そのコマンドの注意対象なし / 1: 注意対象あり / 2: 不正・未対応・打切り等で確定できず**。`check`の1は衝突/gap、`diff`の1は改善を含む何らかの差分、`reachability`の1は非到達または常時抑止、`reachability-staged`の1はscope期待との不一致・未指定の非到達・常時抑止、原文package系の1は記録済みの未解決参照を表す。一部だけ抑止される規則は表示するが、それだけでは1にしない。別CLIの`normkernel`は、背景上の行動不能、義務・禁止の履行不能、又はactiveなのに利用不能な明示的許可があれば、証拠が`VERIFIED`でもexit 1を返す。

## 証拠を保存・再検査する

```bash
python3 -m rulekernel check examples/club-broken.json --certificate examples/club-broken.certificate.json
python3 -m rulekernel verify examples/club-broken.json examples/club-broken.certificate.json
python3 -m rulekernel check examples/club-fixed.json --json
python3 -m rulekernel diff examples/club20/broken.json examples/club20/fixed.json \
  --certificate examples/club20/broken-to-fixed.diff.certificate.json
python3 -m rulekernel verify-diff examples/club20/broken.json examples/club20/fixed.json \
  examples/club20/broken-to-fixed.diff.certificate.json
python3 -m rulekernel reachability examples/club20/fixed.json \
  --certificate examples/club20/fixed.reachability.certificate.json
python3 -m rulekernel verify-reachability examples/club20/fixed.json \
  examples/club20/fixed.reachability.certificate.json
python3 -m rulekernel reachability-staged examples/interpretations/handbook-scope/core.json \
  --scope-expectations examples/interpretations/handbook-scope/scope-expectations.json \
  --expected-scope-expectations-sha256 a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d
python3 -m unittest discover -s tests -v
```

各`verify*`は期待するモデルを必ず別に指定する。証拠はモデル全体のハッシュと結び付き、背景で除外した状況も含めて全入力の処理記録を持つ。枝抜け、偽の例外処理、集計改ざん、モデル差替えを拒否する。

`--max-contexts N`で列挙予算を下げられる（初期値・Cartesian積のハード上限10,000）。これは10,000状況を常に処理できるという保証ではない。入力モデル1 MiB、証拠8 MiBの上限も独立に適用され、先に達した上限で`LIMIT_REACHED`になる。証拠量はコマンド、出力数、有効な規則ID、値、背景適合率などに依存し、左右の出力snapshotを持つ`diff`は特に大きい。factsで絞っていても、初期実装では宣言した全Cartesian積が列挙予算の対象。打切り時に「衝突なし」を返さず、部分証拠も保存しない。

## 原文snapshotをoffline再検査する

```bash
python3 -m rulekernel verify-source \
  examples/sources/fictional-unicode/source-spec.json \
  examples/sources/fictional-unicode/bundle \
  --expected-bundle-sha256 baeba5fb46ac6fb33aa5a31983ea58ab9d2a484cc26222dec256fb26f27bec50
python3 -m rulekernel verify-source \
  examples/sources/penal-code-41/source-spec.json \
  examples/sources/penal-code-41/bundle \
  --expected-bundle-sha256 60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060
```

前者はUnicode・同文反復・Rubyと未解決参照を含む架空原文、後者はe-Govから版を明示して取得した刑法全文XMLとmetadataから本則41条を選んだsnapshot。`verify-source`はcapture specを期待入力としてrawから抽出文と全source unitを再生成し、networkへ接続しない。外部に控えたbundle hashも指定することで、取得記録を含むlockが保存後に変わっていないことを検査する。hashを省略した場合、取得時刻やHTTP記録はpackage内部の自己整合だけとなる。使い方と取得の再実行は[原文package例](examples/sources/README.md)、契約は[原文package仕様](docs/source-package-v0.1.md)にある。

## 手書き解釈をCoreへ変換して再検査する

[2条の架空会員規約](examples/interpretations/member-eligibility/README.md)では、登録者の18歳境界と利用停止の例外を手で解釈し、2規則のCoreへ変換している。保存済みpackageは次でoffline再検査できる。

```bash
python3 -m rulekernel verify-interpretation \
  examples/interpretations/member-eligibility/task.json \
  examples/interpretations/member-eligibility/candidate.json \
  examples/interpretations/member-eligibility/review.json \
  examples/interpretations/member-eligibility/scope-expectations.json \
  examples/interpretations/member-eligibility/compiled.json \
  --source-spec examples/sources/member-eligibility/source-spec.json \
  --source-bundle examples/sources/member-eligibility/bundle \
  --expected-source-bundle-sha256 a63021f7766381a75a7cb8b91f285f47122c1f5d3912a2f6132653e91cf4ac32 \
  --expected-review-sha256 e5e7f865b2195b64057842c70e25b4a78755e1fbaf82061df6c8e64504ad88a0 \
  --expected-scope-expectations-sha256 51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8 \
  --expected-package-sha256 25b6fd536726dce2420f49776e961cb8bb0b78d41b1b8865608dd0fc2335a112
```

`LOWERING_VERIFIED`はCore・来歴・host gold例の再構成成功、`HOST_REVIEW_RECORDED`はreview記録の存在を表す。後者は自然文の読み方や法律上の正しさを証明しない。保存例のreviewはCodexが開発fixtureとして作ったもので、ユーザーや法律専門家の承認ではない。契約と生成コマンドは[解釈IR仕様](docs/interpretation-ir-v0.1.md)にある。

## 刑法41条の限定packを再検査する

[T07刑法41条fixture](examples/interpretations/penal-code-41/README.md)は、保存済み本則41条の1 source unitから、「十四歳に満たない者の行為は、罰しない。」という限定帰結だけを1 Core ruleへ手書きで変換した。13〜15歳、年齢status、行為時statusの12状況で、13歳・両status establishedだけをdefined `true`にする。14歳以上、年齢未知又は行為時点未確定のabsentから、処罰可能性、犯罪成立、責任又は有罪を導かない。

```bash
python3 -m rulekernel verify-interpretation \
  examples/interpretations/penal-code-41/task.json \
  examples/interpretations/penal-code-41/candidate.json \
  examples/interpretations/penal-code-41/review.json \
  examples/interpretations/penal-code-41/scope-expectations.json \
  examples/interpretations/penal-code-41/compiled.json \
  --source-spec examples/sources/penal-code-41/source-spec.json \
  --source-bundle examples/sources/penal-code-41/bundle \
  --expected-source-bundle-sha256 60da7e094d2a8a7d5b1dbb7addf93e9af5ff573fa6cc56f430b499e7b9003060 \
  --expected-review-sha256 944d00c39ec70ba49675e033a44494f3a31e4f10c71566441cfd3edab85171e3 \
  --expected-scope-expectations-sha256 fcf9f74b059bf44b9cca8763a348ded6e19661e90f7fbe1b240ff1a17f3205b8 \
  --expected-package-sha256 e4a2a41eb531715f2c9ad0732f0b447a77e23c039273ae3d655d87ec17c7b95c \
  --json

python3 -m rulekernel verify-reachability-staged \
  examples/interpretations/penal-code-41/core.json \
  examples/interpretations/penal-code-41/staged-reachability.certificate.json \
  --scope-expectations examples/interpretations/penal-code-41/scope-expectations.json \
  --expected-scope-expectations-sha256 fcf9f74b059bf44b9cca8763a348ded6e19661e90f7fbe1b240ff1a17f3205b8 \
  --json
```

前者は`LOWERING_VERIFIED`、Core規則1、host gold 12を返し、`--json`結果に`review_method: manual_fixture_review`と`provisional: true`を含める。後者は別chainとして全12状況、guard/enabled/effective 1/1/1、scope期待一致、attention 0を検査する。どちらも法律専門家レビューや法的意味の正しさを証明しない。固定hash、負例、保証境界は[T07検証記録](docs/verification-t07-2026-09-16.md)にある。

## 義務・禁止・明示的許可を再検査する

[T08架空規範fixture](examples/norms/t08-three-way/README.md)は、状況とBoolean行動候補を分け、
`O(A or B)`、`F(A)`、strict時の`F(B)`、`P(C)`を
[別profile](docs/normative-kernel-v0.1.md)で全列挙する。

```bash
python3 -m normkernel verify \
  examples/norms/t08-three-way/model.json \
  examples/norms/t08-three-way/certificate.json \
  --expected-certificate-sha256 a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a \
  --json
```

8状況のうち対象外4、背景だけで行動不能2、規範上の履行不能1、履行可能1となる。
履行可能な状況にはCを行う候補と行わない候補が各1つあり、明示的許可を義務へ
読み替えていない。checkerはproducerのengineをimportせず、全対象状況と全行動候補を
再構成する。保存証拠は`VERIFIED`だが注意対象があるためexit 1である。
固定hash、負例、保証境界は[T08検証記録](docs/verification-t08-2026-09-16.md)にある。

## scope期待つきで段階別到達可能性を調べる

[星見クラブ資料形式fixture](examples/interpretations/handbook-scope/README.md)は、age 0〜25の範囲で第19条の成立例を期待し、26歳以上を条件とする第20条は非発火を期待する。先に上の`verify-interpretation`相当の検査で原文・review chainを確認し、そのCoreとscope expectationsを次へ渡す。

```bash
python3 -m rulekernel reachability-staged \
  examples/interpretations/handbook-scope/core.json \
  --scope-expectations examples/interpretations/handbook-scope/scope-expectations.json \
  --expected-scope-expectations-sha256 a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d \
  --certificate /tmp/handbook-scope.staged.json

python3 -m rulekernel verify-reachability-staged \
  examples/interpretations/handbook-scope/core.json \
  /tmp/handbook-scope.staged.json \
  --scope-expectations examples/interpretations/handbook-scope/scope-expectations.json \
  --expected-scope-expectations-sha256 a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d
```

52状況で第19条はguard/enabled/effectiveが26、第20条はすべて0となり、期待との一致によりattention 0、exit 0になる。期待を省略した同じ第20条は注意対象のままexit 1。`expected_inactive`はホストが選んだ有限scopeについての記録であり、原文や法律上の非適用を証明しない。T03.1はT05のsource/review chainを再検査しないため、正式な来歴確認には`verify-interpretation`を併用する。契約は[段階別到達可能性仕様](docs/staged-reachability-v0.1.md)、実測と負例は[T03.1検証記録](docs/verification-t03.1-2026-09-15.md)にある。

## 50/100規則の合成workloadを測る

[T06ベンチマーク](benchmarks/t06/README.md)は、13 Bool・8,192状況、50/100規則、guard成立率1/8・7/8、background適合率1・1/8を組み合わせた固定合成モデルを保存する。`check`、`diff`、旧`reachability`、`reachability-staged`をproducer/checker別のfresh subprocessで測り、証拠bytes、時間、`tracemalloc` peak、最後の成功と最初の`LIMIT_REACHED`をhash付きreportへ残した。

```bash
python3 -m benchmarks.t06.generate --check
python3 -m unittest tests.test_t06_benchmark tests.test_t06_measurement tests.test_t06_report_checker -v
python3 -m benchmarks.t06.report_checker \
  benchmarks/t06/results/2026-09-15.json \
  --expected-report-sha256 6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068
```

[正式report](benchmarks/t06/results/2026-09-15.json)のraw SHA-256は`6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068`、body SHA-256は`4c9478c881ec9ac15988a195e3309ba61652361131c087fbdf741c90e53dd7fe`。静的32経路は23件が`VERIFIED`、9件が証拠8 MiBで`LIMIT_REACHED`だった。固定100規則・10出力familyの連続境界はcheck 5,661/5,662、diff 3,172/3,173、reachability 5,646/5,647、staged 3,704/3,705。各組の前者が最後の成功、後者が最初の上限到達で、失敗時は新規certificateを残さず既存targetも変えない。

保存report専用checkerは外部raw hashをanchorにし、現在のsource/model、密度・集計、境界endpoint、report出力と入力pathの分離を再検査する。正式reportは完了workflow 27、`LIMIT_REACHED` workflow 13として`VERIFIED`となる。性能値自体の再実測や、保存されていない静的certificate本体の再検査ではない。

これはT04/T05に由来しない、provenanceが`synthetic_not_t05_derived`の`authored_core` workloadである。自然文の形式化、法的正しさ、一般的な規則数・context数の上限を示さない。測定方法、全数値、endpoint hash、出力pathと長時間bindingの既知制約は[T06検証記録](docs/verification-t06-2026-09-15.md)にある。

## いま扱えること

- Bool、有限Enum、範囲付き整数。型付き比較、and/or/not。
- 部分入力の全補完と、明示した背景条件。
- 条件から定数の決定値を出す規則。
- 対象規則を指定する例外。例外への例外による原則の復活。
- 結論の衝突と、required出力の扱いの抜け。
- 同じ入力・出力領域を持つ2モデルのscope、意味結果、有効な規則ID、衝突/gapの改定差分。
- 条件が成立しない規則、常に抑止される規則、一部だけ抑止される規則の到達可能性診断。
- guard、facts、constraints、両filter、override後の段階件数・4分割・最初のwitnessと、外部hash付きscope期待の照合。
- UTF-8 XML原文、取得記録、抽出text、revision-local source unit ID、0-based半開codepoint spanの固定、外部bundle hash付きoffline再検査。
- 版IDをURLに含むe-Gov XML/metadataの明示取得と法令同一性fieldの照合。失敗時の非公開、既存package非上書き。
- 原文packageに結び付く手書きcandidate、ホストtask・review・scope期待の分離と、十分条件の定数decision・明示的replacement exceptionだけを既存Coreへ変換する限定profile。
- 原文単位のcoverage、引用、参照・issue・assumption依存、Core ruleごとのmanifest由来provenanceを検査し、未解決依存や未承認候補を確定変換しない。
- 保存済み刑法41条の1 source unitを、認定済みの行為時満年齢という仮定の下で1規則へ変換し、13/14/15歳・未知・行為時点未確定の12状況をhost goldと段階別証拠で検査する。開発fixture reviewは`--json`結果の`provisional: true`とpack文書で暫定状態を示す。
- source bundle、review、scope expectations、保存packageの外部hashを使うoffline再検査。producerをimportしないcheckerによるCore・来歴・host gold例の再構成。
- 50/100規則の固定合成matrix、局所では見えないunion衝突とoverride復活sentinel、4検査経路の時間・Python allocation・証拠bytes・連続容量境界のhash付き測定。
- 厳密な入力検査、全列挙証拠、独立再評価、CLI。
- 別profile`finite-norms/1`で、有限状況ごとのBoolean行動候補、義務、禁止、明示的許可を検査する。
- 背景上の行動不能、義務・禁止の履行不能、遵守可能、対象外を分け、許可の行使・非行使候補も保存する。
- 規範producerとは別実装のcheckerが全trace、分類、permission集計を再構成する。

仕様は [kernel-v0.1](docs/kernel-v0.1.md)、[改定差分](docs/diff-v0.1.md)、[到達可能性](docs/reachability-v0.1.md)、[段階別到達可能性](docs/staged-reachability-v0.1.md)、[原文package](docs/source-package-v0.1.md)、[手書き解釈IR](docs/interpretation-ir-v0.1.md)、[有限規範カーネル](docs/normative-kernel-v0.1.md)。既存6規則の[検証結果](docs/verification-2026-09-15.md)、T01〜T03の[検証結果](docs/verification-t01-t03-2026-09-15.md)、T04の[検証結果](docs/verification-t04-2026-09-15.md)、T05の[検証結果](docs/verification-t05-2026-09-15.md)、T03.1の[検証結果](docs/verification-t03.1-2026-09-15.md)、T06の[検証結果](docs/verification-t06-2026-09-15.md)、T07の[検証結果](docs/verification-t07-2026-09-16.md)、T08の[検証結果](docs/verification-t08-2026-09-16.md)に実行記録と信頼範囲がある。T08反映後の全suite 301件と`compileall`が合格している。原文packageの新規公開先は原子的な非上書きを使えるWSLのLinux filesystemとし、`/mnt/c`は安全側に`UNSUPPORTED`で停止する。

有限モデルを直接書く`authored_core`経路に加え、手書き解釈を外側packageで原文・review・scope期待へ結び付ける`interpreted_source`経路を実装した。ただし、保存例の意味対応は開発fixtureのhost goldであり、自然文の正しい読み方や法的妥当性は未検証。旧`reachability`は非到達理由を一つにまとめたまま互換維持し、新しい`reachability-staged`がguard、facts、constraints、overrideを分ける。後者も一般の論理矛盾や正しい法的scopeを自動認定しない。手書きの架空モデルに対する時間なしの義務・禁止・明示的許可は別profileで実装したが、原文・review chainからの規範変換、規範の優先・例外、期限、イベント列、単位計算、一般の法的推論、LLM候補生成、自動意味lint、SAT高速化、画面は未実装。検査結果は指定した有限範囲と照会についてのもので、カーネルの健全性を機械証明したという意味でもない。

## 育てる二つの柱と記録

- 自前の形式モデル検証ソフト。
- 原文を形式化するためのLLM向け規範と二層の中間表現。

小さな版を使いながら扱えるルールを増やす。作業ごとに目的・判断理由・実際の確認・未解決点を残す。

- [現在の状態と次の一歩](STATUS.md)
- [開発日誌](devlog/README.md)
- [小さな規約から刑法・刑事訴訟法へ広げる計画](planning/legal-scale-roadmap.md)
- [作業チケット](planning/legal-scale-tasks.md) / [次の実装への引継ぎ](planning/sol-handoff.md)
- [全体の開発計画](planning/README.md)
- [先行研究・実装の調査報告](research/2026-09-14-landscape.md)
- [出典と読書順](research/sources.md)

[初期のZ3中心の案](research/mvp-design.md)は調査時点の記録。開発では最新の実装仕様・計画・開発日誌を参照する。
