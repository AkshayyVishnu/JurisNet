"""Builds golden_dataset.jsonl from hand-curated, source-traced records.
Run:  python golden_dataset/_build.py
Every source_span is copied verbatim from a document in LEGAL_DATA/ (see _build notes).
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))

# Each record: id, question, question_type, hop_count, difficulty, answer,
# source_span (verbatim substring of primary source body), source_doc_ids,
# primary_source, verification_note, expected_behavior
R = []
def add(**k): R.append(k)

# ---------------- single_hop_metadata (7) ----------------
add(id="Q001", question="In which court and on what date was the petition in 'Sh. Sunder Lal Gupta vs M/S Sahyog Hospitality' decided?",
    question_type="single_hop_metadata", hop_count=1, difficulty="easy",
    answer="The Delhi High Court (Justice Harish Vaidyanathan Shankar) decided it on 27 April 2026.",
    source_span="IN THE HIGH COURT OF DELHI AT NEW DELHI Date of decision: 27.04.2026",
    source_doc_ids=[100420250], primary_source=100420250,
    verification_note="Court name and decision date in judgment header.", expected_behavior="answer")
add(id="Q002", question="Which court decided 'Narayanan Rajendran vs Lekshmy Sarojini' and who authored the judgment?",
    question_type="single_hop_metadata", hop_count=1, difficulty="easy",
    answer="The Supreme Court of India; the judgment was authored by Justice Dalveer Bhandari (Bench: Harjit Singh Bedi, Dalveer Bhandari).",
    source_span="IN THE SUPREME COURT OF INDIA",
    source_doc_ids=[1077888], primary_source=1077888,
    verification_note="Header states Supreme Court; Author: Dalveer Bhandari, J.", expected_behavior="answer")
add(id="Q003", question="Under what petition number and in which High Court was 'Elis Jane Quinlan vs Naveen Kumar Seth' filed?",
    question_type="single_hop_metadata", hop_count=1, difficulty="easy",
    answer="Writ Petition No. 14283 of 2023 in the High Court of Judicature at Bombay (Justice Sandeep V. Marne), decided 10 February 2026.",
    source_span="IN THE HIGH COURT OF JUDICATURE AT BOMBAY CIVIL APPELLATE JURISDICTION WRIT PETITION NO. 14283 OF 2023",
    source_doc_ids=[156512963], primary_source=156512963,
    verification_note="Bombay HC header with WP number.", expected_behavior="answer")
add(id="Q004", question="Which High Court bench decided 'Perumal vs Marudaiyappan' and in what year?",
    question_type="single_hop_metadata", hop_count=1, difficulty="easy",
    answer="The Madurai Bench of the Madras High Court (Justice S. Ramathilagam), on 20 March 2019.",
    source_span="BEFORE THE MADURAI BENCH OF MADRAS HIGH COURT DATED: 20.03.2019",
    source_doc_ids=[144018669], primary_source=144018669,
    verification_note="Madras HC Madurai bench header.", expected_behavior="answer")
add(id="Q005", question="Which High Court decided 'M.P. Krishi Upaj Mandi Samiti vs Prakash Nagpal' and what was the outcome of the petition?",
    question_type="single_hop_metadata", hop_count=1, difficulty="easy",
    answer="The Madhya Pradesh High Court at Jabalpur (Justice Gurpal Singh Ahluwalia); the petition was allowed.",
    source_span="IN THE HIGH COURT OF MADHYA PRADESH AT JABALPUR",
    source_doc_ids=[175747345], primary_source=175747345,
    verification_note="MP HC Jabalpur header; outcome 'the petition is allowed.'", expected_behavior="answer")
add(id="Q006", question="In which High Court was the second appeal in 'Dibakar Naik vs Sri Nuduru @ Prafulla Mohanta' heard, and what was decided?",
    question_type="single_hop_metadata", hop_count=1, difficulty="easy",
    answer="The Orissa High Court at Cuttack (Justice Ananda Chandra Behera); both second appeals were allowed on merit.",
    source_span="ORISSA HIGH COURT : CUTTACK",
    source_doc_ids=[13925394], primary_source=13925394,
    verification_note="Orissa HC header; outcome 'both the 2nd Appeals ... are allowed on merit.'", expected_behavior="answer")
add(id="Q007", question="Which court decided the first appeal in 'Oil And Natural Gas Corporation Limited vs Hindustan Chemicals Company'?",
    question_type="single_hop_metadata", hop_count=1, difficulty="easy",
    answer="The High Court of Gujarat at Ahmedabad (Justices A. S. Supehia and Divyesh A. Joshi); the first appeal was allowed.",
    source_span="IN THE HIGH COURT OF GUJARAT AT AHMEDABAD",
    source_doc_ids=[105140378], primary_source=105140378,
    verification_note="Gujarat HC header.", expected_behavior="answer")

# ---------------- statute_lookup (8) ----------------
add(id="Q008", question="What does Section 9 of the Code of Civil Procedure, 1908 provide about the jurisdiction of civil courts?",
    question_type="statute_lookup", hop_count=1, difficulty="easy",
    answer="Section 9 says civil courts have jurisdiction to try all suits of a civil nature except those whose cognizance is expressly or impliedly barred.",
    source_span="have jurisdiction to try all suits of a civil nature excepting suits of which their cognizance is either expressly or impliedly barred",
    source_doc_ids=[76869205], primary_source=76869205,
    verification_note="Verbatim from Section 9 body.", expected_behavior="answer")
add(id="Q009", question="What power does Section 34 of the CPC give a court regarding interest on a money decree?",
    question_type="statute_lookup", hop_count=1, difficulty="easy",
    answer="Where a decree is for payment of money, the court may order interest at a rate it deems reasonable on the principal sum adjudged, from the date of suit to the date of the decree.",
    source_span="order interest at such rate as the Court deems reasonable to be paid on the principal sum adjudged, from the date of the suit to the date of the decree",
    source_doc_ids=[107990682], primary_source=107990682,
    verification_note="Verbatim from Section 34(1).", expected_behavior="answer")
add(id="Q010", question="Under Section 47 CPC, who decides questions relating to the execution, discharge or satisfaction of a decree?",
    question_type="statute_lookup", hop_count=1, difficulty="medium",
    answer="The court executing the decree decides such questions, not a separate suit.",
    source_span="relating to the execution, discharge or satisfaction of the decree, shall be determined by the Court executing the decree and not by a separate suit",
    source_doc_ids=[119552888], primary_source=119552888,
    verification_note="Verbatim from Section 47(1).", expected_behavior="answer")
add(id="Q011", question="What does Section 100A CPC say about a further appeal from a decision of a Single Judge of a High Court?",
    question_type="statute_lookup", hop_count=1, difficulty="medium",
    answer="Where an appeal from an original or appellate decree/order is heard and decided by a Single Judge of a High Court, no further appeal lies from that judgment and decree.",
    source_span="is heard and decided by a Single Judge of a High Court, no further appeal shall lie from the judgment and decree of such Single Judge",
    source_doc_ids=[144428047], primary_source=144428047,
    verification_note="Verbatim from Section 100A.", expected_behavior="answer")
add(id="Q012", question="What kind of mistakes may be corrected under Section 152 of the CPC?",
    question_type="statute_lookup", hop_count=1, difficulty="easy",
    answer="Clerical or arithmetical mistakes in judgments, decrees or orders, or errors from any accidental slip or omission, may be corrected at any time by the court on its own motion or on a party's application.",
    source_span="Clerical or arithmetical mistakes in judgments, decrees or orders or errors arising therein from any accidental slip or omission may at any time be corrected by the Court",
    source_doc_ids=[150586894], primary_source=150586894,
    verification_note="Verbatim from Section 152.", expected_behavior="answer")
add(id="Q013", question="In which court must a suit be instituted under Section 15 of the CPC?",
    question_type="statute_lookup", hop_count=1, difficulty="easy",
    answer="In the court of the lowest grade competent to try it.",
    source_span="Every suit shall be instituted in the Court of the lowest grade competent to try it",
    source_doc_ids=[167618813], primary_source=167618813,
    verification_note="Verbatim from Section 15.", expected_behavior="answer")
add(id="Q014", question="What does Section 6 of the CPC say about pecuniary jurisdiction?",
    question_type="statute_lookup", hop_count=1, difficulty="easy",
    answer="Except as expressly provided, nothing in the Code gives a court jurisdiction over suits whose subject-matter value exceeds the pecuniary limits of its ordinary jurisdiction.",
    source_span="nothing herein contained shall operate to give any Court jurisdiction over suits the amount or value of the subject-matter of which exceeds the pecuniary limits",
    source_doc_ids=[31796670], primary_source=31796670,
    verification_note="Verbatim from Section 6.", expected_behavior="answer")
add(id="Q015", question="How does Section 2 of the CPC define a 'decree'?",
    question_type="statute_lookup", hop_count=1, difficulty="medium",
    answer="A 'decree' is the formal expression of an adjudication which conclusively determines the rights of the parties on the matters in controversy in the suit, and may be preliminary or final.",
    source_span="\"decree\" means the formal expression of an adjudication which, so far as regards the Court expressing it, conclusively determines the rights of the parties",
    source_doc_ids=[78563457], primary_source=78563457,
    verification_note="Verbatim from Section 2(2).", expected_behavior="answer")

# ---------------- single_hop_holding (6) ----------------
add(id="Q016", question="In the Sunder Lal Gupta arbitration-enforcement matter, what did the Delhi High Court ultimately decide about the petition under Section 17(2)?",
    question_type="single_hop_holding", hop_count=1, difficulty="medium",
    answer="Because the Final Award had been rendered during the petition and had subsumed the interim order, the court held the Section 17(2) reliefs could not be granted and dismissed the petition.",
    source_span="Accordingly, the present Petition stands dismissed",
    source_doc_ids=[100420250], primary_source=100420250,
    verification_note="Operative holding in para 33.", expected_behavior="answer")
add(id="Q017", question="What did the Kerala High Court hold in 'John George vs Stewards Association in India' about an appeal to a Division Bench under Section 100A?",
    question_type="single_hop_holding", hop_count=1, difficulty="medium",
    answer="It held that Section 100-A CPC bars an appeal to a Division Bench against a Single Judge's appellate-jurisdiction judgment, and such appeals filed after 1.7.2002 are not maintainable.",
    source_span="Section 100-A of Code of Civil Procedure bars an appeal to a Division Bench",
    source_doc_ids=[1528427], primary_source=1528427,
    verification_note="Holding in para 12.", expected_behavior="answer")
add(id="Q018", question="What was the Supreme Court's central holding in 'Narayanan Rajendran' about a High Court's powers in a second appeal under Section 100?",
    question_type="single_hop_holding", hop_count=1, difficulty="medium",
    answer="The High Court should not interfere with concurrent findings of fact in a second appeal without formulating a substantial question of law; doing so here was unsustainable, so the SC set aside the HC judgment.",
    source_span="refrain from interfering with the concurrent findings of fact without formulating substantial question of law",
    source_doc_ids=[1077888], primary_source=1077888,
    verification_note="Holding near para 72-73.", expected_behavior="answer")
add(id="Q019", question="In 'Latha Menon vs Ponnamma', what did the Kerala High Court decide about the earlier decision in Seetha Ramachandran?",
    question_type="single_hop_holding", hop_count=1, difficulty="medium",
    answer="It overruled Seetha Ramachandran to the extent it held that sub-rules (1)-(3) of Order XXIII Rule 1 do not apply to interlocutory applications.",
    source_span="The decision in Seetha Ramachandran is overruled to that extent",
    source_doc_ids=[166436152], primary_source=166436152,
    verification_note="Operative overruling line.", expected_behavior="answer")
add(id="Q020", question="In 'Auto Trade And Finance Corporation vs Raj Kishore Sanganaria', why was the execution application dismissed?",
    question_type="single_hop_holding", hop_count=1, difficulty="medium",
    answer="Because the decree-holder approached the wrong forum to execute the decree beyond its territorial limits; such an application must be rejected, so the execution application was dismissed.",
    source_span="he approaches the wrong forum at his own peril",
    source_doc_ids=[181760], primary_source=181760,
    verification_note="Reasoning in final paras.", expected_behavior="answer")
add(id="Q021", question="In 'M.P. Krishi Upaj Mandi Samiti vs Prakash Nagpal', what did the court hold about the application filed under Section 94 CPC?",
    question_type="single_hop_holding", hop_count=1, difficulty="medium",
    answer="The court held the application under Section 94 CPC was not maintainable and set aside the impugned order, giving liberty to file under Order 39 Rule 1 and 2.",
    source_span="the application filed under Section 94 of CPC was not maintainable",
    source_doc_ids=[175747345], primary_source=175747345,
    verification_note="Holding in para 18.", expected_behavior="answer")

# ---------------- multi_hop_judgment_to_provision (8) ----------------
add(id="Q022", question="The second appeal in 'Narayanan Rajendran' was filed under which CPC provision, and what threshold does that provision require?",
    question_type="multi_hop_judgment_to_provision", hop_count=2, difficulty="medium",
    answer="Section 100 CPC. It allows a second appeal to the High Court only if the case involves a substantial question of law.",
    source_span="if the High Court is satisfied that the case involves a substantial question of law",
    source_doc_ids=[1077888, 192138551], primary_source=192138551,
    verification_note="1077888.cited_provisions contains 192138551 (Section 100); span from Section 100 body.", expected_behavior="answer")
add(id="Q023", question="John George's case turned on a CPC provision barring a further appeal from a Single Judge — which provision, and what does it state?",
    question_type="multi_hop_judgment_to_provision", hop_count=2, difficulty="medium",
    answer="Section 100A CPC, which bars any further appeal where an appeal is heard and decided by a Single Judge of a High Court.",
    source_span="no further appeal shall lie from the judgment and decree of such Single Judge",
    source_doc_ids=[1528427, 144428047], primary_source=144428047,
    verification_note="1528427.cited_provisions contains 144428047 (Section 100A); span from Section 100A body.", expected_behavior="answer")
add(id="Q024", question="The execution dispute in 'Elis Jane Quinlan' concerned a foreign decree — which CPC provision governs execution of decrees from reciprocating territories?",
    question_type="multi_hop_judgment_to_provision", hop_count=2, difficulty="medium",
    answer="Section 44A CPC, on execution of decrees passed by courts in a reciprocating territory.",
    source_span="Execution of decrees passed by Courts in reciprocating territory",
    source_doc_ids=[156512963, 51234069], primary_source=51234069,
    verification_note="156512963.cited_provisions contains 51234069 (Section 44A); span from Section 44A title/body.", expected_behavior="answer")
add(id="Q025", question="The ONGC interest dispute was decided under which CPC provision on interest, and what does it empower the court to do?",
    question_type="multi_hop_judgment_to_provision", hop_count=2, difficulty="medium",
    answer="Section 34 CPC, which empowers the court to order reasonable interest on the principal sum of a money decree from the date of suit to the date of the decree.",
    source_span="the Court may, in the decree, order interest at such rate as the Court deems reasonable",
    source_doc_ids=[105140378, 107990682], primary_source=107990682,
    verification_note="105140378.cited_provisions contains 107990682 (Section 34); span from Section 34 body.", expected_behavior="answer")
add(id="Q026", question="In the M.P. Krishi Upaj Mandi case the court found an application under a particular CPC section non-maintainable — what is that section about?",
    question_type="multi_hop_judgment_to_provision", hop_count=2, difficulty="medium",
    answer="Section 94 CPC (supplemental proceedings), which lets the court take certain steps to prevent the ends of justice being defeated.",
    source_span="In order to prevent the ends of justice from being defeated the Court may, if it is so prescribed",
    source_doc_ids=[175747345, 196220096], primary_source=196220096,
    verification_note="175747345.cited_provisions contains 196220096 (Section 94); span from Section 94 body.", expected_behavior="answer")
add(id="Q027", question="The execution in 'Auto Trade And Finance Corporation' raised the question of sending a decree to another court — which CPC provision governs transfer of a decree for execution?",
    question_type="multi_hop_judgment_to_provision", hop_count=2, difficulty="hard",
    answer="Section 39 CPC, under which the court that passed a decree may, on the decree-holder's application, send it for execution to another court of competent jurisdiction.",
    source_span="may, on the application of the decree-holder, send it for execution to another Court",
    source_doc_ids=[181760, 39530104], primary_source=39530104,
    verification_note="181760.cited_provisions contains 39530104 (Section 39); span from Section 39 body.", expected_behavior="answer")
add(id="Q028", question="In 'Latha Menon', which CPC section was used to decide whether Order XXIII Rule 1 applies to interlocutory applications, and what does that section provide?",
    question_type="multi_hop_judgment_to_provision", hop_count=2, difficulty="hard",
    answer="Section 141 CPC, which makes the procedure for suits applicable, as far as it can be, to all proceedings in any court of civil jurisdiction.",
    source_span="The procedure provided in this Code in regard to suits shall be followed, as far as it can be made applicable, in all proceedings in any Court of civil jurisdiction",
    source_doc_ids=[166436152, 133762466], primary_source=133762466,
    verification_note="166436152.cited_provisions contains 133762466 (Section 141); span from Section 141 body.", expected_behavior="answer")
add(id="Q029", question="The Orissa second appeals in 'Dibakar Naik' were filed under which CPC provision, and what does it require for the High Court to interfere?",
    question_type="multi_hop_judgment_to_provision", hop_count=2, difficulty="medium",
    answer="Section 100 CPC; a second appeal lies to the High Court only if the case involves a substantial question of law.",
    source_span="an appeal shall lie to the High Court from every decree passed in appeal by any Court subordinate to the High Court",
    source_doc_ids=[13925394, 192138551], primary_source=192138551,
    verification_note="13925394.cited_provisions contains 192138551 (Section 100); span from Section 100 body.", expected_behavior="answer")

# ---------------- multi_hop_provision_to_cases (5) ----------------
add(id="Q030", question="Which judgments in this corpus are linked to Section 100 CPC (second appeal)? Name at least two.",
    question_type="multi_hop_provision_to_cases", hop_count=2, difficulty="hard",
    answer="Section 100 CPC governs second appeals; corpus cases linked to it include 'Narayanan Rajendran vs Lekshmy Sarojini' (1077888) and 'Gurdev Kaur vs Kaki' (1754551).",
    source_span="Second appeal",
    source_doc_ids=[192138551, 1077888, 1754551], primary_source=192138551,
    verification_note="1077888 and 1754551 appear in 192138551.cases_citedby; span from Section 100 title.", expected_behavior="answer")
add(id="Q031", question="Which corpus cases are linked to Section 44A CPC (execution of foreign decrees)? Give two.",
    question_type="multi_hop_provision_to_cases", hop_count=2, difficulty="hard",
    answer="'Elis Jane Quinlan vs Naveen Kumar Seth' (156512963) and 'Radhamani India Ltd. vs Imperial Garments Ltd.' (1022750).",
    source_span="Execution of decrees passed by Courts in reciprocating territory",
    source_doc_ids=[51234069, 156512963, 1022750], primary_source=51234069,
    verification_note="156512963 and 1022750 appear in 51234069.cases_citedby.", expected_behavior="answer")
add(id="Q032", question="Which corpus cases relate to Section 89 CPC (settlement of disputes outside court)? Name two.",
    question_type="multi_hop_provision_to_cases", hop_count=2, difficulty="hard",
    answer="'Bindu Balakrishna Patali vs Smartowner Services' (14958608) and 'Mrs. Sunandamma P vs M/S GTL Infrastructure' (62240867).",
    source_span="Settlement of disputes outside the Court",
    source_doc_ids=[66488754, 14958608, 62240867], primary_source=66488754,
    verification_note="14958608 and 62240867 appear in 66488754.cases_citedby.", expected_behavior="answer")
add(id="Q033", question="Which corpus cases are connected to Section 16 CPC (suits to be instituted where subject-matter is situate)? Give two.",
    question_type="multi_hop_provision_to_cases", hop_count=2, difficulty="hard",
    answer="'Polotrips India Pvt. Ltd. vs Karnataka Bank Limited' (47339847) and 'GSL (India) Ltd vs Asset Reconstruction Co.' (183942004).",
    source_span="Suits to be instituted where subject-matter situate",
    source_doc_ids=[169730061, 47339847, 183942004], primary_source=169730061,
    verification_note="47339847 and 183942004 appear in 169730061.cases_citedby (Section 16, place of suing).", expected_behavior="answer")
add(id="Q034", question="Name two corpus cases linked to Section 152 CPC (amendment of judgments/decrees for clerical errors).",
    question_type="multi_hop_provision_to_cases", hop_count=2, difficulty="hard",
    answer="'Rakesh Kumar And Others vs Ashok Kumar' (188852815) is among the corpus cases linked to Section 152.",
    source_span="Amendment of judgments, decrees or orders",
    source_doc_ids=[150586894, 188852815], primary_source=150586894,
    verification_note="188852815 appears in 150586894.cases_citedby.", expected_behavior="answer")

# ---------------- multi_hop_bridge (4) ----------------
add(id="Q035", question="Besides 'Narayanan Rajendran', which other corpus judgment also turns on Section 100 CPC, and what do they share?",
    question_type="multi_hop_bridge", hop_count=3, difficulty="hard",
    answer="'Dibakar Naik vs Sri Nuduru' (13925394) also turns on Section 100 CPC; both are second appeals where the scope of High Court interference depends on a substantial question of law.",
    source_span="if the High Court is satisfied that the case involves a substantial question of law",
    source_doc_ids=[1077888, 192138551, 13925394], primary_source=192138551,
    verification_note="Both 1077888 and 13925394 list 192138551 (Section 100) in cited_provisions.", expected_behavior="answer")
add(id="Q036", question="Which other corpus case besides 'John George' relies on Section 100A CPC, and on what common point?",
    question_type="multi_hop_bridge", hop_count=3, difficulty="hard",
    answer="'Asha D/O Bhalchandra Joshi vs National Insurance Co.' (1737105) also relies on Section 100A CPC; both address the maintainability of a further/Letters Patent appeal from a Single Judge.",
    source_span="no further appeal shall lie from the judgment and decree of such Single Judge",
    source_doc_ids=[1528427, 144428047, 1737105], primary_source=144428047,
    verification_note="Both 1528427 and 1737105 list 144428047 (Section 100A) in cited_provisions.", expected_behavior="answer")
add(id="Q037", question="Starting from 'M.P. Krishi Upaj Mandi Samiti', which other corpus case also invokes Section 9 CPC on civil court jurisdiction?",
    question_type="multi_hop_bridge", hop_count=3, difficulty="hard",
    answer="'Latha Menon vs Ponnamma' (166436152) also invokes Section 9 CPC; both engage the principle that civil courts try all civil suits unless cognizance is expressly or impliedly barred.",
    source_span="excepting suits of which their cognizance is either expressly or impliedly barred",
    source_doc_ids=[175747345, 76869205, 166436152], primary_source=76869205,
    verification_note="Both 175747345 and 166436152 list 76869205 (Section 9) in cited_provisions.", expected_behavior="answer")
add(id="Q038", question="'Asha Joshi' and which other corpus case both rely on Section 11 CPC (res judicata)?",
    question_type="multi_hop_bridge", hop_count=3, difficulty="hard",
    answer="'Latha Menon vs Ponnamma' (166436152) also relies on Section 11 CPC; both engage the bar on re-trying a matter already finally decided between the same parties.",
    source_span="No Court shall try any suit or issue in which the matter directly and substantially in issue has been directly and substantially in issue in a former suit",
    source_doc_ids=[1737105, 121631892, 166436152], primary_source=121631892,
    verification_note="Both 1737105 and 166436152 list 121631892 (Section 11) in cited_provisions.", expected_behavior="answer")

# ---------------- comparison_cross_doc (5) ----------------
add(id="Q039", question="How does a first appeal under Section 96 CPC differ from a second appeal under Section 100 CPC?",
    question_type="comparison_cross_doc", hop_count=2, difficulty="medium",
    answer="A first appeal (Section 96) lies from a decree of a court of original jurisdiction and can be on fact and law; a second appeal (Section 100) lies to the High Court only where the case involves a substantial question of law.",
    source_span="an appeal shall lie from every decree passed by any Court exercising original jurisdiction",
    source_doc_ids=[72075529, 192138551], primary_source=72075529,
    verification_note="Span from Section 96; contrast drawn with Section 100's substantial-question-of-law requirement.", expected_behavior="answer")
add(id="Q040", question="What is the difference between Section 10 CPC (stay of suit) and Section 11 CPC (res judicata)?",
    question_type="comparison_cross_doc", hop_count=2, difficulty="hard",
    answer="Section 10 stays the trial of a later suit while an earlier suit on the same matter between the same parties is pending; Section 11 bars trying a suit/issue already heard and finally decided in a former suit. One concerns a pending suit, the other a decided one.",
    source_span="No Court shall proceed with the trial of any suit in which the matter in issue is also directly and substantially in issue in a previously instituted suit",
    source_doc_ids=[85279687, 121631892], primary_source=85279687,
    verification_note="Span from Section 10; contrast drawn with Section 11 (res judicata).", expected_behavior="answer")
add(id="Q041", question="When does a second appeal lie under Section 100 CPC, and in what money-suit situation is it barred by Section 102 CPC?",
    question_type="comparison_cross_doc", hop_count=2, difficulty="medium",
    answer="Section 100 allows a second appeal where a substantial question of law is involved; Section 102 bars any second appeal where the original suit was for recovery of money not exceeding twenty-five thousand rupees.",
    source_span="No second appeal shall lie from any decree, when the subject matter of the original suit is for recovery of money not exceeding twenty-five thousand rupees",
    source_doc_ids=[192138551, 114551302], primary_source=114551302,
    verification_note="Span from Section 102; contrast with Section 100.", expected_behavior="answer")
add(id="Q042", question="Contrast Section 14 CPC and Section 44A CPC in how they treat foreign judgments and decrees.",
    question_type="comparison_cross_doc", hop_count=2, difficulty="hard",
    answer="Section 14 raises a presumption that a certified copy of a foreign judgment was pronounced by a competent court (rebuttable by proving want of jurisdiction); Section 44A allows actual execution in India of a decree of a superior court of a reciprocating territory once its certified copy is filed in a District Court.",
    source_span="The Court shall presume, upon the production of any document purporting to be a certified copy of, a foreign judgment",
    source_doc_ids=[32382254, 51234069], primary_source=32382254,
    verification_note="Span from Section 14; contrast with Section 44A execution.", expected_behavior="answer")
add(id="Q043", question="Compare the outcomes in 'Narayanan Rajendran' and 'Dibakar Naik' regarding High Court interference in second appeals.",
    question_type="comparison_cross_doc", hop_count=2, difficulty="hard",
    answer="In Narayanan Rajendran the Supreme Court faulted the High Court for reversing concurrent findings without a substantial question of law and restored the lower courts' findings; in Dibakar Naik the Orissa High Court itself allowed the second appeals on merit and set aside the lower decrees. Both hinge on the Section 100 substantial-question-of-law gateway.",
    source_span="are allowed on merit",
    source_doc_ids=[1077888, 13925394], primary_source=13925394,
    verification_note="Span from Dibakar Naik outcome; contrast with Narayanan Rajendran holding.", expected_behavior="answer")

# ---------------- doctrine_conceptual (3) ----------------
add(id="Q044", question="Explain the doctrine of res judicata as codified in the CPC.",
    question_type="doctrine_conceptual", hop_count=1, difficulty="easy",
    answer="Res judicata (Section 11 CPC) bars a court from trying any suit or issue that was directly and substantially in issue in a former suit between the same parties (or those claiming under them) and was heard and finally decided by a competent court.",
    source_span="No Court shall try any suit or issue in which the matter directly and substantially in issue has been directly and substantially in issue in a former suit between the same parties",
    source_doc_ids=[121631892], primary_source=121631892,
    verification_note="Section 11 text.", expected_behavior="answer")
add(id="Q045", question="What is the doctrine of res sub judice (stay of suit) under the CPC?",
    question_type="doctrine_conceptual", hop_count=1, difficulty="easy",
    answer="Under Section 10 CPC, a court must not proceed with the trial of a suit whose matter in issue is also directly and substantially in issue in a previously instituted, still-pending suit between the same parties litigating under the same title.",
    source_span="No Court shall proceed with the trial of any suit in which the matter in issue is also directly and substantially in issue in a previously instituted suit",
    source_doc_ids=[85279687], primary_source=85279687,
    verification_note="Section 10 (stay of suit) text.", expected_behavior="answer")
add(id="Q046", question="What modes of out-of-court dispute settlement can a court refer parties to under Section 89 CPC?",
    question_type="doctrine_conceptual", hop_count=1, difficulty="medium",
    answer="Where elements of a settlement exist, the court may formulate terms and refer the dispute to arbitration, conciliation, judicial settlement (including Lok Adalat), or mediation.",
    source_span="(a) arbitration; (b) conciliation; (c) judicial settlement including settlement through Lok Adalat; or (d) mediation",
    source_doc_ids=[66488754], primary_source=66488754,
    verification_note="Section 89(1) modes.", expected_behavior="answer")

# ---------------- temporal_amendment (2) ----------------
add(id="Q047", question="When was Section 12A inserted into the CPC and by which amendment?",
    question_type="temporal_amendment", hop_count=1, difficulty="medium",
    answer="Section 12A was inserted by the Code of Civil Procedure (Amendment) Act, 1976 (Section 70), with effect from 1 February 1977.",
    source_span="Section 70 (w.e.f. 1.2.1977)",
    source_doc_ids=[40166762], primary_source=40166762,
    verification_note="Amendment note at end of Section 12A body.", expected_behavior="answer")
add(id="Q048", question="What is the pecuniary threshold in Section 102 CPC, and how was it modified for Uttar Pradesh?",
    question_type="temporal_amendment", hop_count=1, difficulty="medium",
    answer="Section 102 bars a second appeal where the money sought does not exceed twenty-five thousand rupees; for Uttar Pradesh this was substituted with 'fifty thousand rupees' by U.P. Act 16 of 2019.",
    source_span="the words \"fifty thousand rupees\" shall be substituted. [U.P. act 16 of 2019]",
    source_doc_ids=[114551302], primary_source=114551302,
    verification_note="UP state amendment note in Section 102 body.", expected_behavior="answer")

# ---------------- case_to_case_citation (2) ----------------
add(id="Q049", question="Which Constitution Bench Supreme Court decision does 'John George vs Stewards Association' discuss on the Letters Patent / Section 100A question?",
    question_type="case_to_case_citation", hop_count=2, difficulty="medium",
    answer="It discusses 'P.S. Sathappan (Dead) by L.Rs. v. Andhra Bank Ltd.' (12214027), a Constitution Bench judgment.",
    source_span="P.S. Sathappan (Dead) by L.Rs. v. Andhra Bank Ltd. and Ors.",
    source_doc_ids=[1528427, 12214027], primary_source=1528427,
    verification_note="1528427.cited_judgements contains 12214027; both in corpus.", expected_behavior="answer")
add(id="Q050", question="Which Supreme Court decision on interest does the ONGC judgment rely on?",
    question_type="case_to_case_citation", hop_count=2, difficulty="medium",
    answer="It relies on 'Central Bank of India vs. Ravindra And Others', (2002) 1 SCC 367 (doc 1902234).",
    source_span="Central Bank of India vs. Ravindra And Others",
    source_doc_ids=[105140378, 1902234], primary_source=105140378,
    verification_note="105140378.cited_judgements contains 1902234; both in corpus.", expected_behavior="answer")

# ---------------- negative_unanswerable (4) ----------------
add(id="Q051", question="What is the punishment for murder under Section 302 of the Indian Penal Code?",
    question_type="negative_unanswerable", hop_count=0, difficulty="medium",
    answer="Not answerable from this corpus. The corpus is limited to the Code of Civil Procedure, 1908 and civil judgments; it contains no Indian Penal Code provisions. The system should abstain.",
    source_span="", source_doc_ids=[], primary_source=None,
    verification_note="Out-of-domain (criminal law); no IPC documents in corpus.", expected_behavior="abstain")
add(id="Q052", question="What does Section 500 of the Code of Civil Procedure, 1908 provide?",
    question_type="negative_unanswerable", hop_count=0, difficulty="medium",
    answer="Not answerable. There is no Section 500 in the CPC, 1908, and no such provision exists in the corpus. The system should abstain rather than fabricate text.",
    source_span="", source_doc_ids=[], primary_source=None,
    verification_note="Non-existent provision; trap for hallucination.", expected_behavior="abstain")
add(id="Q053", question="Summarize the Supreme Court's 2027 ruling on cryptocurrency taxation.",
    question_type="negative_unanswerable", hop_count=0, difficulty="medium",
    answer="Not answerable. The corpus ends in mid-2026 and contains no cryptocurrency-taxation judgment; the system should abstain.",
    source_span="", source_doc_ids=[], primary_source=None,
    verification_note="Out-of-period and out-of-domain.", expected_behavior="abstain")
add(id="Q054", question="What bail conditions under Section 437 CrPC are discussed in the corpus judgments?",
    question_type="negative_unanswerable", hop_count=0, difficulty="medium",
    answer="Not answerable. The corpus is civil (CPC) and contains no Criminal Procedure Code material or bail discussion; the system should abstain.",
    source_span="", source_doc_ids=[], primary_source=None,
    verification_note="Out-of-domain (criminal procedure).", expected_behavior="abstain")

out = os.path.join(HERE, "golden_dataset.jsonl")
with open(out, "w", encoding="utf-8") as f:
    for r in R:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"Wrote {len(R)} records to {out}")
