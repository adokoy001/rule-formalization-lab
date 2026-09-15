# T09実装担当への引継ぎ

更新日: 2026-09-16
対象: リポジトリルート

## 依頼文

> Rule Formalization Labの[段階拡張計画](legal-scale-roadmap.md)と[作業チケット](legal-scale-tasks.md)に従い、次はT09「有限の手続・時間」を完成させてください。既存T08の`finite-norms/1`を黙って読み替えず、時間の意味と証拠形式を新しい版又は別profileとして先に固定してください。実法令はまだ増やさず、架空の申請手続を小さく実装してください。

## 着手時に読むもの

1. [AGENTS.md](../AGENTS.md)
2. [STATUS.md](../STATUS.md)
3. [T08規範仕様](../docs/normative-kernel-v0.1.md)
4. [T08検証記録](../docs/verification-t08-2026-09-16.md)
5. [T08架空fixture](../examples/norms/t08-three-way/README.md)
6. [既知課題](known-issues.md)のK12〜K14、K16、K18、K19
7. [本日の開発日誌](../devlog/2026-09-16.md)

## 確認済みの基準

- T08は入力状況とBoolean行動候補を分け、義務、禁止、明示的許可を時間なしで扱う。
- 保存fixtureは全8状況、admitted 4、各8行動候補。対象外4、背景不能2、規範上の履行不能1、履行可能1。
- model SHA-256は`0d71e04b1c43038754638a6e52dca63771318902564df8cca278f495486ed839`、certificateは`a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a`。
- T08専用38件、全suite 301件、`compileall`が合格。既存T06 report checkerも外部hash付きで`VERIFIED`。
- T08は`authored_normative_core`専用で、T05の原文/review chain、時間、優先関係、実法令には未接続。

## T09の最小scope

架空の申請について、申請、受領、審査、決定、通知を候補eventとして区別する。観測終了は候補traceが選ぶeventにせず、contextごとに固定された外生的なevidence horizonとする。最初は5〜10規範と少数のevent slot・時刻だけにする。

仕様化してから実装する項目:

- eventの主体、kind、時刻、同時刻時の順序又は同時性。
- 時刻の整数単位と基準点。秒・時間・日を暗黙変換しない。
- 期限の起算event、包含境界、期限直前・一致・直後。
- 観測済みprefixと観測終了座標をcontext側へ固定し、候補traceの選択で動かせないようにする。
- 観測済みprefixと矛盾しない将来completionだけを候補にし、期限前の未観測を違反と確定しない。
- 背景上不可能なevent列、規範上履行不能なevent列、遵守可能なevent列。
- 一部期間の禁止が、後半に履行候補を残す対照。禁止終了後の候補復活は規範overrideとは呼ばない。
- event欠落、起算点未確定、観測打切りを問題なしへ落とさないstatus。
- 状況ごとのevent列存在という量化順と、完全列挙の上限。

初期profileの有限化契約も先に固定する。

- modelが最大8個のevent slotと、各slotで許す有限な`(tick, phase)`候補を列挙する。各slotは全trace中0回又は1回だけで、同kindの反復・多重度は`UNSUPPORTED`とする。
- 観測済みslotは発生座標を固定する。未観測の将来slotだけが、明示候補座標又はabsentを選ぶ。候補trace数は各将来slotの`1 + 許可座標数`の積として列挙前に計算する。
- `tick`は整数時間、`phase`は同一tick内の順序とする。同じ`(tick, phase)`のevent群は同時であり、kind順はcanonical保存順にだけ使って意味上の先後を作らない。
- 初期上限候補は1 contextあたり4,096 trace、context×trace 100,000組、モデル1 MiB、証拠8 MiBとする。最終値は仕様・境界テストと一緒に固定し、上限超過を部分的な成功へしない。
- 初期fixtureは宣言event kindについて`closed_prefix`を使い、観測終了以前の未記録を不発生として固定する。過去の未記録を不明とするopen-world観測は別profile又は後続版まで`UNSUPPORTED`とし、黙って不発生へ変換しない。

## 必須fixtureと負例

少なくとも次を独立goldとして先に書く。

1. 期限直前、期限一致、期限直後。
2. 申請時起算と受領時起算が異なる例。
3. 同時刻eventの順序が結果へ影響する場合と、同時性として扱う場合。
4. 提出義務の期間前半だけを禁止し、後半に履行候補が残る例。
5. 観測終了が期限前、期限一致、期限後の未提出。
6. 起算eventがない又は時刻未確定の例。
7. 一つの状況だけ履行不能で、別状況の成功が隠さない例。
8. producerの境界比較、event順、観測判定を一つずつ壊し、checkerが拒否する変異。
9. 証拠のbranch欠落、重複、順序、集計、witness、model/hash改ざん。
10. 上限・I/O失敗・既存path・公開競合で部分証拠を残さない例。

## 実装上の境界

- 実時間全体を有限候補時刻の検査で網羅したと呼ばない。有限domainを明示する。
- 「直ちに」「相当」「やむを得ない」等を数値へ変換しない。
- 未観測、未履行、期限違反、規範集合の履行不能を別状態にする。
- 権限・裁量、制裁、救済、規範overrideは意味を定めるまで受理しない。
- T10の刑事訴訟法へT09の架空profileをそのまま法解釈として流用しない。
- producerとcheckerは式評価、event列生成、期限境界、分類、集計を別実装にする。
- T06の歴史的reportへ結ぶ既存`rulekernel` sourceを変更する必要がある場合は、過去reportと現在sourceの状態を混同しない。

## 完了条件

- 仕様、最小fixture、producer、独立checker、CLI、保存証拠、正例・負例が揃う。
- 期限・観測の各境界を全候補から再構成できる。
- `VERIFIED`と、履行不能・違反・未確定等の診断を分離する。
- 既存全suite、T08保存anchor、T06 report checkerが回帰する。
- 実行コマンド、件数、hash、失敗例、未対応、次の一歩を検証記録、日誌、STATUSへ残す。

## 基準コマンド

```bash
cd /path/to/rule-formalization-lab
python3 -m unittest discover -s tests -v
python3 -m compileall -q rulekernel normkernel tests benchmarks
python3 -m normkernel verify \
  examples/norms/t08-three-way/model.json \
  examples/norms/t08-three-way/certificate.json \
  --expected-certificate-sha256 a61cbda1b788a60e11988cda9a8468b14b5bf4e098f701c1435c867dda448b8a \
  --json
python3 -m benchmarks.t06.report_checker \
  benchmarks/t06/results/2026-09-15.json \
  --expected-report-sha256 6bda457de5e19dbcbd74bb7df50f528b1c4dd6ca1e1040a972af35c7d3af1068
```

T08の`verify`は証拠が`VERIFIED`でも、保存した背景不能・規範上の履行不能を報告するためexit 1が正しい。exit 0を期待して基準を弱めない。
