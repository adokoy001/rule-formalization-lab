# 20規則・改定差分・到達可能性の検証記録

実施日: 2026-09-15。WSL Ubuntu / Python 3.14.4。
対象はT01〜T03で、既存の[`finite-decisions/1`](kernel-v0.1.md)の意味は変更していない。

## 完成した範囲

| チケット | 成果 | 独立検査 |
|---|---|---|
| T01 | 20規則・416状況の星見クラブ問題版/修正版と、原文から作った期待表 | 既存のdecision checkerで全416状況・6出力を再検査 |
| T02 | 改定前後のscope・意味・規則ID・衝突・gap差分 | [`verify_diff`](../rulekernel/diff_checker.py)が左右モデルから全証拠を再構成 |
| T03 | 規則ごとのenabled/effective件数と4種類の到達可能性分類 | [`verify_reachability`](../rulekernel/reachability_checker.py)が全行・全集計を再構成 |

差分と到達可能性のproducer/checkerは、列挙、式評価、override解決、集計の実装を共有しない。
モデルの構文・型検査、canonical JSON、hash、上限定数は共通の信頼対象である。

## 実行したコマンド

```bash
python3 -m unittest discover -s tests -v

python3 -m rulekernel check examples/club20/broken.json \
  --certificate examples/club20/broken.certificate.json --json
python3 -m rulekernel check examples/club20/fixed.json \
  --certificate examples/club20/fixed.certificate.json --json

python3 -m rulekernel diff examples/club20/broken.json examples/club20/fixed.json \
  --certificate examples/club20/broken-to-fixed.diff.certificate.json --json
python3 -m rulekernel verify-diff examples/club20/broken.json examples/club20/fixed.json \
  examples/club20/broken-to-fixed.diff.certificate.json --json

python3 -m rulekernel reachability examples/club20/broken.json \
  --certificate examples/club20/broken.reachability.certificate.json --json
python3 -m rulekernel verify-reachability examples/club20/broken.json \
  examples/club20/broken.reachability.certificate.json --json
python3 -m rulekernel reachability examples/club20/fixed.json \
  --certificate examples/club20/fixed.reachability.certificate.json --json
python3 -m rulekernel verify-reachability examples/club20/fixed.json \
  examples/club20/fixed.reachability.certificate.json --json
```

全**124テスト**が複数回合格した（2.803〜3.416秒、読取り専用の最終監査では2.966秒）。旧6規則の50テストに加え、
20規則教材14件、差分34件、到達可能性20件、拡張CLI 6件を含む。

## T01: 20規則教材

原文・有限範囲・決定表・具体例は、モデルの実行前に
[`examples/club20/README.md`](../examples/club20/README.md)で固定した。

| 対象 | 全状況 / admitted | 資格衝突 | 料金gap | 貸出衝突 | その他の照会 |
|---|---:|---:|---:|---:|---:|
| 問題版 | 416 / 416 | 32 | 32 | 4 | 0 |
| 修正版 | 416 / 416 | 0 | 0 | 0 | 0 |

問題版で少なくとも一つの問題がある状況は、重複を除くと36状況。
18・19歳の32状況では資格衝突と料金gapが同時に生じ、25歳・既存会員・講習未修了の4状況では貸出上限が衝突する。

## T02: 問題版から修正版への差分

| 出力 | 意味結果の変化 | 解消の内訳 | 新規問題 | 規則IDだけの変化 |
|---|---:|---:|---:|---:|
| eligible | 32 | 衝突解消32 | 0 | 0 |
| fee_yen | 32 | gap解消32 | 0 | 0 |
| loan_limit | 4 | 衝突解消4 | 0 | 0 |
| その他 | 0 | 0 | 0 | 0 |

適用範囲の変化は0。意味結果の変化は合計68出力×状況ペアで、入力状況の重複を除くと36状況。
衝突解消・gap解消は意味変化の内訳なので、68へ再加算しない。
同一モデル同士のCLI差分は全照会0・終了コード0になることも確認した。

## T03: 到達可能性

| 版 | 条件不成立 | 常時抑止 | 一部抑止 | 条件成立時は常に有効 |
|---|---:|---:|---:|---:|
| 問題版 | 1 | 0 | 7 | 12 |
| 修正版 | 1 | 0 | 7 | 12 |

両版の非到達規則はR20だけで、`age >= 26`という条件に対して宣言範囲が0〜25歳だからである。
R20を一般に不要と判断した結果ではない。教材の複製を26歳まで広げるテストではR20が発火する。
一部抑止の7規則は、明示した例外が成立する状況だけeffectiveでなくなる規則である。

CLIの`reachability`と`verify-reachability`は、`unreachable`または
`always_suppressed`が1件でもあれば終了コード1を返す。`partially_suppressed`だけでは1にしない。
そのため今回の両版は、証拠検査に成功しつつR20の診断により終了コード1となる。

## 保存した証拠

| 証拠 | bytes | SHA-256 |
|---|---:|---|
| [問題版の基礎検査](../examples/club20/broken.certificate.json) | 89,654 | `ed7444bf518f6dccdd9585cc2b1c24804258ef8f3290d9aedfe0c7416ac753f1` |
| [修正版の基礎検査](../examples/club20/fixed.certificate.json) | 89,423 | `0fe96986689843458f24489400ba63cad584290e761fee4662e7f3e039a4a2c3` |
| [問題版→修正版の差分](../examples/club20/broken-to-fixed.diff.certificate.json) | 402,524 | `cd8d9345fc18d04c4caaf9da50c89a5855831d336ef36d412c5f7391b11c66ef` |
| [問題版の到達可能性](../examples/club20/broken.reachability.certificate.json) | 95,133 | `a0eee4a1cd0fefdfcd696b2a91055252e23ba6995ace59539a2b48ca8fe9984b` |
| [修正版の到達可能性](../examples/club20/fixed.reachability.certificate.json) | 95,302 | `1f4a418d62e6e9c149eca2f70f5cdf6d1adc5f439be5e20632722fb0ea3b2b9f` |

全てcanonical UTF-8 JSONの実測値で、証拠上限8,388,608 bytes以内。
保存直後に別CLIコマンドで再検査し、作成時と再検査時のcertificate hashが一致した。

同じ416状況で、差分証拠402,524 bytesは基礎証拠2件の平均89,538.5 bytesの
約4.50倍だった。これは現在の教材における比率で、規則数、出力数、有効な規則ID、
値、背景適合率が変わる別モデルへそのまま外挿しない。10,000状況は列挙ハード上限であり、
8 MiBの証拠上限まで常に処理できるという保証ではない。

モデルhash:

```text
broken 20aeabd231fccfc1e6773c7eb21a9600110b6997e3d4cc475f7b106658c080ae
fixed  1d6268421c56fb113efd1f52a20a4662a34d49d6fea22f1fd5990eb4fb84d05c
```

## 負例と残る信頼対象

テストでは全出力状態遷移、小さなoverride DAGの独立oracle、背景の共通範囲0、
規則配列順・ID変更、trueと1の型すり替え、行・件数・最初のwitness・hash・版の改ざんを確認した。
producer側へ比較境界の誤り、入力枝の欠落、偽集計を意図的に入れた証拠も独立checkerが拒否した。
上限到達時は部分証拠を保存せず、結果を確定しない。

`VERIFIED`は、指定モデルと証拠の完全な再評価が一致したという意味である。
原文からモデルへの手写しが正しいこと、修正内容が現実の規約として妥当なこと、
カーネルの健全性が機械証明されたことは含まない。義務・禁止・許可、時間、原文IR、LLM形式化、実法令はこの段階では未実装。

## Opus 5による独立レビュー

2026-09-15の[協働掲示板の追加レビュー](review-notes-2026-09-15.md)では、
別環境から124テスト、5証拠hash、2モデルhashが再確認され、追加の改ざん6種もexit 2で拒否された。
同レビューが報告した合成モデル別の実効上限値は、元モデル/生成器がこのプロジェクトに保存されていないため、
こちらで再現済みの製品仕様とは扱わない。T06でgenerator/config/hashを固定して照会別に測り直す。

レビューが指摘した到達不能理由の不足も[K15/T03.1](../planning/legal-scale-tasks.md)へ登録した。
現v0.1は非到達を保守的にexit 1とする。原文に結び付いたscope期待と段階別件数を新しい証拠版で
独立検査できるまで、「宣言範囲外だから問題なし」と自動分類しない。
