# 架空会員規約の手書き解釈

T05の最小fixture。原文、非信頼candidate、ホスト管理review、scope expectations、生成Coreと来歴を一つの再現可能な経路にした。

原文:

1. 登録者で18歳以上の者は会員資格を持つ。
2. 前条にかかわらず、利用停止中の者は会員資格を持たない。

[固定原文package](../../sources/member-eligibility/)には2単位と、2条の「前条」から1条へのresolved referenceを保存している。

## ファイル

- [`task.json`](task.json): 原文hashと有限scopeを所有するホストtask。
- [`candidate.json`](candidate.json): 手書きの非信頼解釈候補。承認・scope期待は持てない。
- [`review.json`](review.json): Codexが開発fixtureとして作ったhost review記録と5境界例。ユーザーや法律専門家による承認ではない。
- [`scope-expectations.json`](scope-expectations.json): T03.1が照合する全Core ruleの到達期待。
- [`core.json`](core.json): compiled packageから取り出した段階別検査対象Core。
- [`compiled.json`](compiled.json): 独立checker通過後のlegacy Core、hash chain、manifest由来provenance。
- [`staged-reachability.certificate.json`](staged-reachability.certificate.json): scope期待つき段階別到達可能性の保存証拠。

Coreは`age` 0〜25、`registered`、`suspended`を入力とする。`suspended -> registered`を背景制約にし、104 Cartesian状況のうち78状況が対象。`eligible`はrequiredではないため、第1条から17歳の反対値を推測せず`absent`のままにする。

境界gold:

| 入力 | 期待 |
|---|---|
| 登録済み・17歳・停止なし | absent |
| 登録済み・18歳・停止なし | true |
| 登録済み・25歳・停止なし | true |
| 登録済み・18歳・停止中 | false |
| 未登録・18歳・停止なし | absent |

再検査コマンドとhashは[解釈IR仕様](../../../docs/interpretation-ir-v0.1.md)、実行結果と負例は[T05検証記録](../../../docs/verification-t05-2026-09-15.md)に固定した。成功時の`LOWERING_VERIFIED`と`HOST_REVIEW_RECORDED`は別の状態である。

T03.1の段階別検査では、全積104、facts適合104、constraints適合78、両方適合78。成人規則はenabled 16/effective 8の一部抑止、利用停止例外はenabled 26/effective 26で、両方とも`expected_in_scope`と一致してattention 0となる。保存certificateのSHA-256は`89aee1333f46ddfccf0bfdeac09565297a00b2cd96a9b0fcdf323a0b4ff3202b`。

```bash
python3 -m rulekernel verify-reachability-staged \
  examples/interpretations/member-eligibility/core.json \
  examples/interpretations/member-eligibility/staged-reachability.certificate.json \
  --scope-expectations examples/interpretations/member-eligibility/scope-expectations.json \
  --expected-scope-expectations-sha256 51dc9ee5f607d6b93d100872b7f3e38b6fe320440c875780a84d47b47575f5a8
```

この段階別checkerはT05の原文・review chainを再構築しないため、原文からの来歴確認には`verify-interpretation`も併用する。scope期待はホストによる固定有限scopeの判断であり、原文や法的解釈の正しさを証明しない。詳細は[T03.1検証記録](../../../docs/verification-t03.1-2026-09-15.md)にある。
