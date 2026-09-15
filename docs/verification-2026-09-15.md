# 自前カーネル v0.1 の検証記録

実施日: 2026-09-15。WSL Ubuntu / Python 3.14.4。対象仕様は [finite-decisions/1](kernel-v0.1.md)。

この文書は最初の6規則・50テスト時点の基準記録。後続の20規則、改定差分、到達可能性と全124テストは
[T01〜T03の検証記録](verification-t01-t03-2026-09-15.md)に分けて保存した。

## 実行した確認

```bash
python3 -m unittest discover -s tests -v
```

**50テストが全て合格**。最終実行のunittest表示は0.257秒。小さなfixtureの回帰結果であり、実用規模の性能測定ではない。

| テスト | 確認した範囲 |
|---|---|
| [test_kernel.py](../tests/test_kernel.py) | 34テスト。架空規約、未知入力、矛盾facts、空背景、空入力、型と式、例外、全域性、証拠改ざん、上限 |
| [test_exhaustive.py](../tests/test_exhaustive.py) | 7テスト。3規則の8種類のDAG × 8種類の発火条件 × 8種類の帰結 = 512組を含む。Boolean真理値表、整数比較境界、Enum順、探索器の意図的な誤実装、依存検査 |
| [test_cli.py](../tests/test_cli.py) | 9テスト。CLIの保存→再検査、終了コード、入力上書き拒否、不正JSON/Unicode、照会0件表示、証拠生成と検査のbyte上限 |

512組は、固定した3規則・前向き3候補辺の限定集合。任意の論理式や任意規模のモデルを全数検査したという意味ではない。

探索側のgeをgtへ意図的に変更する変異、およびBoolのtrue側を列挙しない変異は、別のcheckerで `CERTIFICATE_INVALID`になった。手書きの証拠改ざんだけでなく、誤った探索実装が作る結果も拒否することを確認した。

## 保存した証拠と再実行

```bash
python3 -m rulekernel check examples/club-broken.json --certificate examples/club-broken.certificate.json
python3 -m rulekernel check examples/club-fixed.json --certificate examples/club-fixed.certificate.json
python3 -m rulekernel verify examples/club-broken.json examples/club-broken.certificate.json --json
python3 -m rulekernel verify examples/club-fixed.json examples/club-fixed.certificate.json --json
```

| 対象 | 全状況 / 背景適合 | 資格衝突 | 料金gap | 証拠検査 / 終了コード |
|---|---:|---:|---:|---|
| [問題のある版](../examples/club-broken.json) | 52 / 52 | 4 | 4 | VERIFIED / 1 |
| [修正版](../examples/club-fixed.json) | 52 / 52 | 0 | 0 | VERIFIED / 0 |

他の照会は両版とも0件。前者の4状況は18・19歳 × 学生区分2通り。同じ4状況に2種類の問題があり、異なる8状況という意味ではない。

保存済みの成果物:

- [問題版の証拠](../examples/club-broken.certificate.json) / [再検査結果](../examples/club-broken.verification.json)
- [修正版の証拠](../examples/club-fixed.certificate.json) / [再検査結果](../examples/club-fixed.verification.json)

モデル全体のSHA256（canonical JSON）:

```text
broken e404e8936e39c10006cc53a7f2b3c85d47b52855d887bfc6885519e1ace07d56
fixed  51071c237e159792e0d5895addc65e4de52aefe184c8702c5602555c1171fc57
```

検証結果JSONは今回の実行記録。モデルや実装を変更した後は、保存済み結果の表示だけを信用せず、上記verifyを再実行する。

## 実装と残る信頼対象

- [model.py](../rulekernel/model.py): JSON、型、参照、循環、factsの矛盾、式・入力の上限。
- [engine.py](../rulekernel/engine.py): Cartesian積の列挙、短絡式評価、再帰とメモ化による例外処理、証拠生成。
- [checker.py](../rulekernel/checker.py): 再帰での独自列挙、全引数の式評価、反復による例外処理、結果の再集計と全証拠照合。
- [CLI](../rulekernel/__main__.py): 独立確認後の表示・証拠保存と、既存証拠の再検査。

checkerはengineをimportせず、探索・式評価・例外処理・集計コードを共有しない。構文・型validator、canonical JSON、ハッシュは共有する。ランタイムのimportをASTで確認し、外部ライブラリへの依存がないこともテストした。

共通信頼対象は、モデルの構文・型検査、仕様の正しさ、JSON/ハッシュ、Python処理系、標準ライブラリと実行環境。独立実装でも同じ仕様誤りを共有しうる。**カーネルの健全性・完全性に関する機械証明は未実施**。テスト結果と、今回の個別証拠の検査を分けて扱う。

証拠は全contextの平坦な列挙記録。checkerも全域を評価するため、高速な証明検査方式ではない。モデル1 MiB、証拠8 MiB、Cartesian積10,000状況をそれぞれ上限とし、先に達した上限で停止する。10,000状況を常に処理できるという保証、時間制限、大規模性能保証はまだ設けていない。

## 既知課題への対応範囲

以下はこの限定profileで実装・テストした部分。24課題全体の完了ではない。

| 課題 | 今回の対策 | 残る範囲 |
|---|---|---|
| K01/K02/K03 | 未指定値の全補完、異値facts拒否、空背景拒否 | 四値の根拠台帳・原文解釈の不整合管理 |
| K06/K07 | 明示辺だけの例外、非発火時の維持、例外への例外で復活 | 時間窓・規範の部分override |
| K08 | override循環拒否、入力以外の式参照拒否 | 定義・別名・規範参照は構文自体が未対応 |
| K09 | 全入力状況ごとの決定衝突検査 | 履行可能性の量化交替は未実装 |
| K14 | 厳密整数/Bool型、64bit範囲の境界比較 | 算術、単位、日付、丸め |
| K15 | required出力だけのgap、空背景の別状態 | 到達可能性の専用照会 |
| K16/K18/K19 | 独立全域再評価、改ざん/枝抜け拒否、版/hash/予算確認 | checkerの形式証明、CNF変換、原文承認台帳 |

義務・禁止・許可・時間に関するK04/K05/K10〜K13、SAT変換K17、原因極小化K20、LLM/原文対応K21〜K24は未実装。
