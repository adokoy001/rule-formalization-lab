# T11実装担当への引継ぎ

更新日: 2026-09-16
対象: リポジトリルート

## 依頼文

> Rule Formalization Labの段階拡張計画に従い、次はT11「刑法の次の論点」を進めてください。刑法43条・44条等から一つの狭い問いを選び、公式版原文、参照先、裁量、条件付き効果、未確定な事実認定を先に棚卸ししてください。既存のdecision・permission・deadlineへ同じ意味だとして押し込まず、必要な最小意味論を架空例で固定してから実法令packへ接続してください。

## 着手時に読むもの

1. [AGENTS.md](../AGENTS.md)
2. [STATUS.md](../STATUS.md)
3. [段階拡張計画](legal-scale-roadmap.md)と[作業チケット](legal-scale-tasks.md)
4. [T07刑法41条pack](../examples/interpretations/penal-code-41/README.md)と[検証記録](../docs/verification-t07-2026-09-16.md)
5. [T08規範仕様](../docs/normative-kernel-v0.1.md)
6. [T09時間仕様](../docs/procedure-time-kernel-v0.1.md)
7. [T10検証記録](../docs/verification-t10-2026-09-16.md)
8. [既知課題](known-issues.md)

## 確認済みの基準

- T01〜T10とT03.1は各限定profileで完了し、全358テストと`compileall`が合格している。
- T07は刑法41条の一方向の十分条件だけを扱い、14歳以上から処罰可能性を導かない。
- T08のpermissionはhard normを解除せず、権限・裁量を表す意味論ではない。
- T09は一回限りの有限event slotと離散候補時刻に限定する。
- T10は手作業review・数値期限・binding整合の検査であり、semantic lowering又は法的結論ではない。

## T11の最初の作業

1. 現行施行版の刑法43条・44条と直接参照先を公式sourceで確認し、revisionを固定する。
2. 初回packで答える問いを一つだけ選ぶ。例として、実行着手・未遂という事実評価を入力済み前提にし、43条前段の効果候補を扱う案がある。
3. 必要的効果と裁量的な選択肢を区別する。複数選択肢を同時義務又は単一Booleanの衝突にしない。
4. 「実行に着手」「遂げなかった」「自己の意思」「中止した」等の評価概念を自動判定しない。入力前提又は`unresolved`として記録する。
5. 44条の各則依存を固定分母として棚卸しし、未取得・未形式化の参照をfalseへしない。
6. 実法令へ接続する前に、同じ選択・裁量意味論の架空fixture、境界例、変異テスト、独立checkerを作る。

## 完了条件

- source revision、全source unit、参照、coverage、task、candidate、review、model、certificateが結び付く。
- 採用した必要効果、許される選択肢、未解決評価を別fieldで表示する。
- 一つの選択肢が可能であることを、全選択肢の同時要求へ変えない。
- 条件が成立しない場合から既遂・無罪・処罰可能性等の反対結論を導かない。
- producer非依存checker、外部hash、正例・負例、全体回帰、検証記録、日誌、STATUS更新が揃う。

## 維持する回帰

```bash
cd /path/to/rule-formalization-lab
python3 -m unittest discover -s tests -v
python3 -m compileall -q rulekernel normkernel procedurekernel tests benchmarks
python3 -m procedurekernel.t10_binding_cli examples/procedures/t10-criminal-procedure-203-205/task.json examples/procedures/t10-criminal-procedure-203-205/candidate.json examples/procedures/t10-criminal-procedure-203-205/review.json examples/procedures/t10-criminal-procedure-203-205/model.json examples/procedures/t10-criminal-procedure-203-205/certificate.json examples/procedures/t10-criminal-procedure-203-205/binding.json examples/sources/criminal-procedure-55-203-206/source-spec.json examples/sources/criminal-procedure-55-203-206/bundle --expected-binding-sha256 e76cf9be471e45a5f83cb35083c15470f8f4ff3be6c1424ad3e97aec3b126811 --json
```

T11は論点選定と意味論の不足が判明した時点で小さく分けてよい。未対応を隠すために既存の型へ近似しない。
