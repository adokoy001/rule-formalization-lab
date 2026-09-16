# T09 架空申請手続

実在しない申請手続を使い、有限のevent候補、期限、禁止期間、観測終了を試す保存fixtureである。
自然文は[`source.txt`](source.txt)、形式モデルは[`model.json`](model.json)、完全列挙証拠は
[`certificate.json`](certificate.json)にある。

5個のslotは申請、受領、審査、決定、通知である。5規範は、申請起算の受領期限、受領起算の
審査期限、審査の初期禁止期間、受領起算の決定期限、決定起算の通知期限を表す。4背景制約は
先行eventを欠く後続eventと逆順を排除する。

## 固定した境界

| context | 確認点 |
|---|---|
| `decision_before_deadline` | 決定が期限前 |
| `decision_at_deadline` | 包含期限と一致 |
| `decision_after_deadline` | 同tickの後phaseで期限超過 |
| `different_anchors` | 申請起算と受領起算を混同しない |
| `same_tick_phase_order` | 同tickでもphase差に先後がある |
| `simultaneous_non_strict` | 同一座標は同時で、non-strict順序を満たす |
| `simultaneous_strict_background_failure` | 同一座標はstrict順序を満たさない |
| `partial_prohibition_later_candidate` | 禁止中候補を退け、禁止後候補を残す |
| `notice_missing_*` | 排他的観測終了が期限前・一致・後 |
| `anchor_missing` | 起算eventなしを未確定として残す |
| `anchor_time_unresolved` | 起算eventの時刻`null`を未確定として残す |

禁止後の候補復活は時間窓の終了であり、優先関係やoverrideではない。

## 再検査

```bash
python3 -m procedurekernel verify \
  examples/procedures/t09-application/model.json \
  examples/procedures/t09-application/certificate.json \
  --expected-certificate-sha256 \
  4d034bb60c7a038fde3747ef26202e6b14a7d560360da200a2efbd438a71bca7 \
  --json
```

証拠は`VERIFIED`になるが、意図的な違反・背景不能・未確定contextを含むためexit codeは1である。
`VERIFIED`は宣言された有限モデルと証拠の一致だけを意味し、現実のルールの正しさ、法的判断、
又は連続時間の網羅を意味しない。

SHA-256:

```text
source.txt       4acc5e7adecac51cade440c5beae5053952ea9c32835a2f75146acec859e929c
model.json       e614d11bad5a2cd4026c5dc15aac94c547f9233d0acbe32bff0022848218a67c
certificate.json 4d034bb60c7a038fde3747ef26202e6b14a7d560360da200a2efbd438a71bca7
```
