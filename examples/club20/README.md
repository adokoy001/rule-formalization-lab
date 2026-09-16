# 星見クラブの20規則教材

T01用の架空規約。実在の法律・団体の規約ではない。以下の原文・採用範囲・期待例をモデルの実行前に固定し、人が `finite-decisions/1` の `authored_core` へ写す。[旧6条教材](../README.md)はそのまま残す。

モデルは [broken.json](broken.json) と [fixed.json](fixed.json)。両方ちょうど20規則で、各規則の `source` に下表の原文を付ける。自然文を自動形式化する機能や、自然文との意味対応を機械証明する機能は使っていない。

## 対象と意味

| 入力 | 採用する値 |
|---|---|
| age | 0〜25歳の整数 |
| event | 特別企画の参加区分か：false / true |
| member | 既存会員として登録されているか：false / true |
| student | 学生区分か：false / true |
| training | 機材講習を修了した区分か：false / true |

全積は **26 × 2⁴ = 416状況**。背景条件とfactsは空で、全416状況を対象とする。Boolの未指定をfalseにせず両値へ補完する。既存会員の登録区分 `member` と今回の会員資格判定 `eligible` は別であり、入力を出力から計算しない。どちらの値もあり得る入力として扱う。

全参加者について、資格 `eligible`、料金 `fee_yen`、貸出上限 `loan_limit`、預り金 `deposit_yen`、資料形式 `handbook` が決まることを `required: true` で指定する。バッジ印 `badge` は任意出力で、印のない参加者をgapにはしない。資格の有無によらず料金等は全参加者に適用する。

金額は円単位の固定値、貸出上限は個数の固定値。返金、実際の貸出行動、支払義務、期限はモデル化しない。資料形式はEnum `digital / paper`。適用条件はすべて入力だけを参照する。

## 原文を先に固定する

「〜にかかわらず」は記載した規則を明示的に打ち消す。例外を打ち消す例外が有効な場合、原則が復活する。[カーネルの意味論](../../docs/kernel-v0.1.md)に従い、推移的な打消しは追加しない。

| ID | 問題版の原文 | 修正版で変える箇所 |
|---|---|---|
| R01 | 第1条　18歳以上の参加者は、会員資格を持つ。 | 変更なし |
| R02 | 第2条　20歳未満の参加者は、会員資格を持たない。 | 「20歳未満」を「18歳未満」へ |
| R03 | 第3条　18歳未満の参加者の参加料金は、500円とする。 | 変更なし |
| R04 | 第4条　20歳以上の参加者の参加料金は、1000円とする。 | 「20歳以上」を「18歳以上」へ |
| R05 | 第5条　20歳以上の学生の参加料金は、第4条にかかわらず800円とする。 | 「20歳以上」を「18歳以上」へ |
| R06 | 第6条　特別企画に参加する20歳以上の学生の参加料金は、第5条にかかわらず1000円とする。 | 「20歳以上」を「18歳以上」へ |
| R07 | 第7条　18歳以上の学生には、記念バッジの配布対象印を付ける。 | 変更なし |
| R08 | 第8条　既存会員には、記念バッジの配布対象印を付ける。 | 変更なし |
| R09 | 第9条　機材講習を修了した参加者の貸出上限は、3個とする。 | 変更なし |
| R10 | 第10条　機材講習を修了していない参加者の貸出上限は、1個とする。 | 変更なし |
| R11 | 第11条　16歳未満の参加者の貸出上限は、第9条及び第10条にかかわらず0個とする。 | 変更なし |
| R12 | 第12条　特別企画に参加する16歳未満の機材講習修了者の貸出上限は、第11条にかかわらず3個とする。 | 変更なし |
| R13 | 第13条　25歳以上の既存会員の貸出上限は、第9条にかかわらず2個とする。 | 「第9条」を「第9条及び第10条」へ |
| R14 | 第14条　既存会員ではない参加者の預り金は、1000円とする。 | 変更なし |
| R15 | 第15条　既存会員の預り金は、0円とする。 | 変更なし |
| R16 | 第16条　既存会員ではない学生の預り金は、第14条にかかわらず500円とする。 | 変更なし |
| R17 | 第17条　特別企画に参加する、既存会員ではない学生の預り金は、第16条にかかわらず1000円とする。 | 変更なし |
| R18 | 第18条　学生に配布する資料の形式は、電子版とする。 | 変更なし |
| R19 | 第19条　学生ではない参加者に配布する資料の形式は、紙版とする。 | 変更なし |
| R20 | 第20条　26歳以上の参加者に配布する資料の形式は、第19条にかかわらず電子版とする。 | 変更なし |

R20は今回の年齢範囲では条件が一度も成立しない。26歳以上を対象外としたためであり、あらゆる範囲で不要な条文と判断したわけではない。第19条・第20条は後に[原文packageと手書き解釈の小さいfixture](../interpretations/handbook-scope/README.md)へ切り出し、T03.1でguardからoverride後までの段階件数とホスト管理scope期待を照合した。

## 手で導いた検査件数

| 照会 | 問題版 | 修正版 | 原文からの理由 |
|---|---:|---:|---|
| eligible の衝突 | 32 | 0 | 18・19歳にR01とR02。2歳分 × 16区分 |
| fee_yen のgap | 32 | 0 | 18・19歳はR03〜R06のどれも成立しない。2歳分 × 16区分 |
| loan_limit の衝突 | 4 | 0 | 25歳・既存会員・講習未修了にR10とR13。event × studentの4区分 |
| その他の衝突・required gap | 0 | 0 | 下の決定表で全出力が一意に決まる |

衝突件数とgap件数は別照会の件数。合計68を「問題のある異なる状況数」とは呼ばない。資格衝突と料金gapの32状況は同じなので、少なくとも一つの問題がある状況は **36**。

入力の辞書順は `age, event, member, student, training`。最初の資格衝突と料金gapはindex 288の `(18,false,false,false,false)`。最初の貸出衝突はindex 404の `(25,false,true,false,false)`。

### 結論の決定表

以下は原文から整理した期待値であり、エンジン出力から生成した表ではない。テストのgoldはこの表と具体例を用いる。

- 資格：修正版は18歳未満false、18歳以上true。問題版は18・19歳でfalseとtrueの両方。
- 料金：18歳未満500円。成人区分の境界は問題版20歳・修正版18歳。境界以上は通常1000円、特別企画ではない学生は800円。特別企画の学生はR06がR05を止め、R04の1000円も復活する。問題版18・19歳は値がない。
- 貸出：16歳未満は通常0個。特別企画の講習修了者ならR12がR11を止め、R09の3個も復活する。16歳以上は講習修了3個・未修了1個。ただし25歳以上の既存会員は2個。問題版のこの区分で講習未修了ならR10の1個も残る。
- 預り金：既存会員0円。非会員は通常1000円、特別企画ではない学生500円。特別企画の非会員学生はR17がR16を止め、R14の1000円も復活する。
- 資料：今回の範囲では学生digital、学生以外paper。R20は非発火。
- バッジ：18歳以上の学生、または既存会員にtrue。両条件が成立しても同値のtrueが二つあるだけで衝突しない。それ以外は値なし（任意出力）。

### 固定した具体例

入力欄は `(age,event,member,student,training)`。結論の括弧は値の集合であり、`—`は値なし。

| 入力 | 版 | 資格 | 料金 | 貸出 | 預り金 | 資料 | バッジ |
|---|---|---|---|---|---|---|---|
| (18,F,F,F,F) | 問題 | {F,T} | — | {1} | {1000} | {paper} | — |
| (18,F,F,F,F) | 修正 | {T} | {1000} | {1} | {1000} | {paper} | — |
| (19,F,T,T,T) | 問題 | {F,T} | — | {3} | {0} | {digital} | {T} |
| (19,F,T,T,T) | 修正 | {T} | {800} | {3} | {0} | {digital} | {T} |
| (20,F,F,T,T) | 両方 | {T} | {800} | {3} | {500} | {digital} | {T} |
| (20,T,F,T,T) | 両方 | {T} | {1000} | {3} | {1000} | {digital} | {T} |
| (15,F,F,T,T) | 両方 | {F} | {500} | {0} | {500} | {digital} | — |
| (15,T,F,T,T) | 両方 | {F} | {500} | {3} | {1000} | {digital} | — |
| (16,F,F,F,F) | 両方 | {F} | {500} | {1} | {1000} | {paper} | — |
| (25,F,T,F,F) | 問題 | {T} | {1000} | {1,2} | {0} | {paper} | {T} |
| (25,F,T,F,F) | 修正 | {T} | {1000} | {2} | {0} | {paper} | {T} |

## 実行する

リポジトリ直下から実行する。問題版はexit 1、修正版はexit 0が期待結果。`VERIFIED`は結果の証拠確認であって、問題0件という意味ではない。

```bash
python3 -m rulekernel check examples/club20/broken.json --json
python3 -m rulekernel check examples/club20/fixed.json --json
python3 -m rulekernel check examples/club20/broken.json --certificate /tmp/club20-broken.certificate.json --json
python3 -m rulekernel verify examples/club20/broken.json /tmp/club20-broken.certificate.json --json
python3 -m rulekernel diff examples/club20/broken.json examples/club20/fixed.json --json
python3 -m rulekernel reachability examples/club20/broken.json --json
python3 -m unittest discover -s tests -p test_club20.py -v
python3 -m unittest discover -s tests -v
```

416状況は全積上限10,000の4.16%。テストでは各証拠が1 MiB未満であることも確認し、製品上限8 MiBに余裕を残す。

## 2026-09-15の確認結果

原文・期待例を固定した後でモデルを実行し、上の期待件数と全416状況の6出力が一致した。期待値を実行結果に合わせて変更していない。

| 項目 | 問題版 | 修正版 |
|---|---:|---:|
| 規則数 | 20 | 20 |
| 全積 / 背景適合数 | 416 / 416 | 416 / 416 |
| モデルファイルのbytes | 10,265 | 10,312 |
| 証拠のcanonical UTF-8 bytes | 89,654 | 89,423 |
| 証拠上限8,388,608 bytesまでの余裕 | 8,298,954 | 8,299,185 |

証拠bytesは `len(canonical_json(certificate).encode("utf-8"))` の実測。保存ファイルに末尾改行等を加えたサイズとは分ける。

- `analyze → verify`：両版ともVERIFIED。問題版は資格衝突32・料金gap32・貸出衝突4、修正版は全11照会で0。
- 一時ディレクトリへのCLI証拠保存 → 別Pythonプロセスの `verify`：両版とも成功し、証拠hashと照会結果が一致。終了コードは問題版1・修正版0。
- 専用テスト14件：合格。全状況の手書き決定表、独立した具体例、3種類の修正の個別適用、部分factsの残るBool全補完、例外・原則復活、規則配列順、上限を確認した。
- 既存分を含む全64テスト：合格。旧6条CLIも再実行し、52状況・問題版の資格衝突4/料金gap4・修正版の全照会0・終了コード1/0を確認した。
- R20の範囲依存を確認する専用テストでは、テスト内の複製モデルだけを26歳まで拡張した。26歳・非学生ではR20が発火してR19を抑止し、digitalとなる。これは本教材の416状況の件数には含めない。

T02/T03の実装後に、基礎検査の[問題版証拠](broken.certificate.json)・[修正版証拠](fixed.certificate.json)、
[問題版→修正版の差分証拠](broken-to-fixed.diff.certificate.json)、
[問題版](broken.reachability.certificate.json)・[修正版](fixed.reachability.certificate.json)の到達可能性証拠を保存した。
全て別CLIコマンドで再検査済み。差分と到達可能性の件数・hash・全124テストの記録は
[T01〜T03検証記録](../../docs/verification-t01-t03-2026-09-15.md)を参照する。

## T12のcompact基礎証拠

2026-09-16に、整数境界で意味が同じ入力を重み付きセルへまとめる別形式の証拠を追加した。問題版は416状況から80セル・35,360 bytes、修正版は416状況から64セル・28,309 bytesになった。旧全数証拠からのbytes減少はそれぞれ60.56%、68.34%。照会件数と最初の具体witnessは旧全数証拠と一致する。

```bash
python3 -m compactkernel estimate examples/club20/broken.json --json
python3 -m compactkernel check examples/club20/broken.json \
  --certificate /tmp/club20-broken.compact.jsonl --json
python3 -m compactkernel verify examples/club20/broken.json \
  /tmp/club20-broken.compact.jsonl \
  --expected-certificate-sha256 1ac37d4180f1ea16a16e4c900f356070e3c756233cfadf1cd650318102b7e18f --json
python3 -m compactkernel verify examples/club20/fixed.json \
  examples/club20/fixed.compact.jsonl \
  --expected-certificate-sha256 dff0123181c20d6df46bd3b9662c378352796b44404fe32b49fa90dd63c3c8b8 --json
```

`check` の出力先には未作成のpathを指定する。compact CLIは既存証拠を置き換えないため、同じ例を再実行するときは別名を使う。

保存した [問題版compact証拠](broken.compact.jsonl) と [修正版compact証拠](fixed.compact.jsonl) はstrict JSON Linesで、別実装のcheckerがpartition、全cell、集計、witness、具体case列のcommitmentを再構成する。形式、上限、信頼境界は[compact証拠仕様](../../docs/compact-certificate-v0.1.md)、実測と負例は[T12検証記録](../../docs/verification-t12-2026-09-16.md)を参照する。

この経路は基礎 `check` だけを対象とする。具体状況10,000と証拠8 MiBの上限は維持し、整数変数同士を比較するモデルは整数軸を全列挙へ戻す。`diff`、`reachability`、norm、procedureはこの形式で圧縮しない。

モデルhash：

- 問題版：`20aeabd231fccfc1e6773c7eb21a9600110b6997e3d4cc475f7b106658c080ae`
- 修正版：`1d6268421c56fb113efd1f52a20a4662a34d49d6fea22f1fd5990eb4fb84d05c`

この教材で検査するのは決定値の衝突とrequired出力のgap。原文との意味対応、実際の行為・義務・期限、26歳以上や新しい区分は検査結果の保証範囲に含めない。
