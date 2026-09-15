# 星見クラブ資料形式の手書き解釈

T03.1用の小さいT05 fixture。Club20 fixedの第19条・第20条と同じ原文・条件・結論を、[固定原文package](../../sources/handbook-scope/)から既存Coreへ変換する。

入力は `age` 0〜25と `student`、出力はoptionalなEnum `handbook = digital | paper`。第19条は非学生ならpaper、第20条はage 26以上なら第19条をoverrideしてdigitalとする。「第19条」参照は原文packageとcandidateの両方でresolvedである。

| Core rule | Host期待 | 段階別到達可能性 |
|---|---|---|
| `IR_P_HANDBOOK_PAPER` | `expected_in_scope` | enabled 26 / effective 26 |
| `IR_P_HANDBOOK_AGE_EXCEPTION` | `expected_inactive` | enabled 0 / effective 0 |

全Cartesian積は52状況で、factsとconstraintsは空。学生にはこの2条だけから値を補わないため `handbook` はabsentとなる。T03.1の段階別経路では、第19条のguard/enabled/effectiveが各26、第20条が各0となり、外部固定した期待と一致してattention 0、exit 0になる。旧reachability v0.1は互換経路として第20条を`unreachable`と報告し、scope期待を照合しない。

Host goldは、0歳・25歳の非学生がpaper、同じ年齢の学生がabsentとなる4例。26歳は宣言domain外なのでgold入力へ入れていない。保存reviewはCodexが開発fixtureとして作った記録で、ユーザーや法律専門家による承認ではない。

- [task.json](task.json): source hashと有限scopeを所有するhost task。
- [candidate.json](candidate.json): 手書きの非信頼解釈候補とresolved reference。
- [review.json](review.json): host review記録と4つのsemantic gold。
- [scope-expectations.json](scope-expectations.json): R19=`expected_in_scope`、R20=`expected_inactive`。
- [core.json](core.json): compiled packageから取り出した段階別検査対象Core。
- [compiled.json](compiled.json): 独立checker通過後のCore、来歴、hash chain。
- [staged-reachability.certificate.json](staged-reachability.certificate.json): scope期待つき段階別到達可能性の保存証拠。

| 項目 | SHA-256 |
|---|---|
| source bundle | `52ca5a149fe1e901b62854ac4b12c613e0ab8261e54a4b6a932f2963bd0dc8e4` |
| source-unit manifest | `1170350e93942928d90c68101169a7560b0f280997018e542963cbc614081c11` |
| task | `4a59b8b543655f8099a6f0467f194508cd83a106bbb4bf8bc0a5fdca6de5a8b8` |
| candidate | `02c8d88521f37dfc66cd9b073a364a5ffcb0ef13cda4096f2a57f8bdb81fa69d` |
| review | `493d006fdd1642e7cee25494d144a79a32f06451479d15acd8dac24433cbe2f4` |
| interpretation snapshot | `b952329e09b8c447b1ab3d438643a75b829fbdbd7d0c30d5bbad0c8f41e21293` |
| scope | `5cdb9b458a606fbaf54e9f5aa9dae7ab0470b770dadf73a4a61e4c398269fd6a` |
| scope expectations | `a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d` |
| Core model | `3baed24f29c0822257db9e12920fbc75be2852b99d99e8f588b1d1bcb84554d6` |
| compiled package | `7d0f1f28e2d84bffffac1281cf5954780e4cbb7ece75aee3f5d00d609608056a` |
| staged certificate | `d6e9bf6758ad5277b70accb54647a77b5e3f6f06969974438b4a9a2761082453` |

JSON文書のhashは契約どおりcanonical JSONへ計算する。保存staged certificateはcanonical JSONそのものなので、ファイルbytesのSHA-256も表の値と一致する。

~~~bash
python3 -m rulekernel verify-interpretation examples/interpretations/handbook-scope/task.json examples/interpretations/handbook-scope/candidate.json examples/interpretations/handbook-scope/review.json examples/interpretations/handbook-scope/scope-expectations.json examples/interpretations/handbook-scope/compiled.json --source-spec examples/sources/handbook-scope/source-spec.json --source-bundle examples/sources/handbook-scope/bundle --expected-source-bundle-sha256 52ca5a149fe1e901b62854ac4b12c613e0ab8261e54a4b6a932f2963bd0dc8e4 --expected-review-sha256 493d006fdd1642e7cee25494d144a79a32f06451479d15acd8dac24433cbe2f4 --expected-scope-expectations-sha256 a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d --expected-package-sha256 7d0f1f28e2d84bffffac1281cf5954780e4cbb7ece75aee3f5d00d609608056a

python3 -m rulekernel verify-reachability-staged examples/interpretations/handbook-scope/core.json examples/interpretations/handbook-scope/staged-reachability.certificate.json --scope-expectations examples/interpretations/handbook-scope/scope-expectations.json --expected-scope-expectations-sha256 a9f95803953cdf36a641dc3cf8023b0833b3b94b450da44572f71ff7fcd12b5d
~~~

T03.1 checkerはT05のsource/task/candidate/review chainを再構築しない。原文からの来歴を伴う確認では、上の2コマンドを併用する。`expected_inactive`はホストが選んだ固定有限scopeに対する判断であり、原文や法的な非適用を証明しない。
