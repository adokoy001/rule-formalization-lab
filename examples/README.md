# 架空の星見クラブ規約

実在の法律や団体の規約ではない。自然文を人が形式化した `authored_core` の教材であり、自然文からの自動変換例ではない。

原文package、非信頼candidate、host review、scope expectations、Core変換を分けたT05の例は[架空会員規約の手書き解釈](interpretations/member-eligibility/README.md)にある。[星見クラブ資料形式](interpretations/handbook-scope/README.md)ではT03.1の段階別到達可能性と`expected_inactive`の照合を、保存certificateまで再現できる。どちらもLLMによる自動変換や専門家承認の例ではない。

- [問題のある版](club-broken.json)
- [境界を揃えた版](club-fixed.json)
- [実装契約](../docs/kernel-v0.1.md)

各JSONの `rules[].source` に6条の原文を添えた。年齢は整数の0〜25歳、学生かどうかは真偽値とする。全参加者について会員資格と参加料金が決まることを、モデルの `required: true` で指定した。バッジの配布対象印は任意出力であり、印がない場合は料金のような適用漏れとして数えない。

これは手作業で選んだ対象範囲と全域性の条件であり、6条の原文だけから自動的に確定した設定ではない。会員資格の有無によらず全参加者に料金規則を適用する。未成年にも料金があるのはそのため。

## 期待する結果

年齢26通り × 学生区分2通りで、両版とも52状況を検査する。`facts` は空であり、年齢や学生区分の未指定を偽として扱わず、全補完を検査する。

| 検査 | 問題のある版 | 境界を揃えた版 |
|---|---:|---:|
| 会員資格の衝突 | 4状況（18・19歳 × 学生区分2通り） | 0 |
| 会員資格の適用漏れ | 0 | 0 |
| 料金の衝突 | 0 | 0 |
| 料金の適用漏れ | 4状況（18・19歳 × 学生区分2通り） | 0 |
| バッジの衝突 | 0 | 0 |

最初の衝突・料金の適用漏れは、どちらも `age=18, student=false`（case index 36）。会員資格にはR1のtrueとR2のfalseが同時に出る。料金には有効な規則がない。

学生割引のR5はR4を明示的に打ち消す。両方の規則が有効なまま料金800円と1000円が衝突する、という解釈にはしない。R5の条件を満たさない参加者にはR4が通常どおり適用される。

修正版ではR2を「18歳未満」に、R4とR5を「18歳以上」に揃えた。17歳は資格なし・500円、18歳以上は資格あり・通常1000円または学生800円となる。18歳以上の学生にはバッジ印も付く。

ここで0件なのは指定した52状況と検査種別の範囲内の結果。原文の意味の完全性や、範囲外の年齢・条件についての保証ではない。`VERIFIED` は結果を裏付ける証拠の確認を意味し、問題が0件という意味ではない。

## コマンドから確認する

リポジトリ直下で実行する。

```bash
python3 -m rulekernel check examples/club-broken.json --certificate /tmp/club-broken-certificate.json
python3 -m rulekernel verify examples/club-broken.json /tmp/club-broken-certificate.json
python3 -m rulekernel check examples/club-fixed.json
```

終了コードは0が範囲内の検出なし、1が問題検出（証拠の確認は成功）、2が未確定または拒否。問題のある版の終了コード1は、この教材の期待する結果。機械可読の結果には `--json` を付ける。

## Pythonから確認する

リポジトリ直下で実行する。

```python
from rulekernel.model import load_json
from rulekernel.engine import analyze
from rulekernel.checker import verify

model = load_json("examples/club-broken.json")
certificate = analyze(model)
verification = verify(model, certificate)
print(verification)
```

テストは `python3 -m unittest discover -s tests -v` で実行する。
