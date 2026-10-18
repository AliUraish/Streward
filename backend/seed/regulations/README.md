# Regulations rule pack (demo)

> **Demo rule pack, not legal advice.** These records support a hackathon demo. The summaries are our own plain-English wording, written after reading the cached official text. They are not a complete statement of the law and must not be relied on for compliance decisions. Always read the official source and take professional advice.

- `regulations.json`: 63 records in the contract §5 shape (REALITY-CONTRACT-4.md §5), plus a few additive fields (see below). There are 24 for England and Victoria, 18 for Japan, which cover the Tomioka Silk Mill (REALITY-CONTRACT-5.md §6), and 21 California comparison records (`jurisdiction: "US-CA"`, `binding: false`). None of the three sites is in California, so these show what would apply if a site were there.
- `obligations-suggested.json`: one suggested obligation per scenario and site, each citing regulation ids from `regulations.json`. There are twenty: six for Bristol and Myer, plus five for the Tomioka scenarios, the Tomioka fire-safety duty and Bristol's side of `x-heritage`, plus nine California comparison entries (`obl-ca-*`, `binding: false`). The comparison entries have no `relatedSeedObligationIds`, so they never attach to a seed obligation.
- The PDFs are cached in `backend/data/regulations/`, which is gitignored. Each record's `pdfPath` is relative to `backend/data`.

Every `pageHint` was checked by extracting the PDF text (pypdf 5.7.0) and confirming that the provision's heading or opening words appear on that page. For the Japanese records, every sentence of each cited article was also checked against the official e-Gov XML of the same revision.

## Files

| `pdfPath` | Instrument and version | Official PDF URL | Bytes | SHA-256 | Licence | Retrieved (UTC) |
| --- | --- | --- | ---: | --- | --- | --- |
| `regulations/uksi_2000_128.pdf` | Pressure Systems Safety Regulations 2000 (SI 2000/128), latest available (revised) version, PDF generated 2025-07-23, no known outstanding effects. 23 pages. | https://www.legislation.gov.uk/uksi/2000/128/data.pdf | 580,536 | `2937dbd04f144f315fd2628edf5e5701ccd61b786afbbc732c4906c317fc9c99` | OGL v3.0 | 2026-10-18T04:20:18Z |
| `regulations/uksi_1992_3004.pdf` | Workplace (Health, Safety and Welfare) Regulations 1992 (SI 1992/3004), latest available (revised) version, PDF generated 2025-07-25, no known outstanding effects. 23 pages. | https://www.legislation.gov.uk/uksi/1992/3004/data.pdf | 340,236 | `4f5c872b9427ac8fd7045116649a8a87151b70aa2b647e01094a04a479bdc553` | OGL v3.0 | 2026-10-18T04:20:18Z |
| `regulations/ukpga_1974_37.pdf` | Health and Safety at Work etc. Act 1974 (c. 37), latest available (revised) version, PDF generated 2026-07-24. 172 pages. | https://www.legislation.gov.uk/ukpga/1974/37/data.pdf | 9,330,885 | `aaa8032a8bee06355dba318261420609efecf8bb1944e7f45b64d53173a3dbcb` | OGL v3.0 | 2026-10-18T04:20:19Z |
| `regulations/vic_sr_2017_22_ohs_regulations_v017.pdf` | Occupational Health and Safety Regulations 2017 (Vic), S.R. No. 22/2017, Authorised Version No. 017, incorporating amendments as at 29 July 2026 (in force). 633 pages. | https://content.legislation.vic.gov.au/sites/default/files/2026-07/17-22sra017-authorised.pdf | 2,760,542 | `52f038c0e2bb0b9e73346a0990b59da47d54049f0984d811a34d09560aefced5` | © State of Victoria; personal use only (verbatim below) | 2026-10-18T04:34:07Z |
| `regulations/vic_sr_2018_38_building_regulations_v031.pdf` | Building Regulations 2018 (Vic), S.R. No. 38/2018, Authorised Version No. 031, incorporating amendments as at 1 September 2026 (in force). 564 pages. | https://content.legislation.vic.gov.au/sites/default/files/2026-09/18-38sra031-authorised.PDF | 3,074,422 | `9f9e00fdb75aff49d290c66c08fa15b7ebbb1b0ee72dbe90ab0eda2b8ea40bf1` | © State of Victoria; personal use only (verbatim below) | 2026-10-18T04:37:59Z |
| `regulations/vba_practice_note_esm02.pdf` | Building Practice Note ESM-02: Maintenance of Essential Safety Measures, Victorian Building Authority, Version 2.0 (28 June 2021), watermarked UNDER REVIEW (file titled 15 Feb 2024). Guidance, not law. 6 pages. | https://www.bpc.vic.gov.au/__data/assets/pdf_file/0013/21541/Building-ESM-02-Maintenance-of-Essential-Safety-Measures-UNDER-REVIEW-15-Feb-2024.pdf | 1,468,285 | `5a5ba9c5acdf2ec8e6161cba451feb16565bcc61f00eea062a628b73790ff404` | © VBA; no copying without consent (verbatim below) | 2026-10-18T04:42:54Z |
| `regulations/jp_act_1950_214_cultural_properties_r20250601.pdf` | Act on Protection of Cultural Properties (文化財保護法, Act No. 214 of 1950), current version on e-Gov, revision 325AC0100000214_20250601_504AC0000000068 (amended up to Act No. 68 of 2022, in force 1 June 2025). PDF 横一段 (horizontal), 38 pages. | https://laws.e-gov.go.jp/data/Act/325AC0100000214/606456_1/325AC0100000214_20250601_504AC0000000068_h1.pdf | 414,485 | `44d8e87c510a34b076d0eed1ee335f5f4f303f707ea2b5c959a833dc85395725` | PDL1.0 (verbatim below) | 2026-10-18T06:48:55Z |
| `regulations/jp_act_1948_186_fire_service_r20250601.pdf` | Fire Service Act (消防法, Act No. 186 of 1948), current version on e-Gov, revision 323AC1000000186_20250601_504AC0000000068 (amended up to Act No. 68 of 2022, in force 1 June 2025). PDF 横一段, 38 pages. | https://laws.e-gov.go.jp/data/Act/323AC1000000186/606172_1/323AC1000000186_20250601_504AC0000000068_h1.pdf | 463,969 | `bb17fde586711665a971e0577f5e34c972faaef1c2f5ccd78860ed53ec5f6d92` | PDL1.0 | 2026-10-18T06:48:35Z |
| `regulations/jp_co_1961_37_fire_service_order_r20251001.pdf` | Enforcement Order of the Fire Service Act (消防法施行令, Cabinet Order No. 37 of 1961), current version on e-Gov, revision 336CO0000000037_20251001_507CO0000000085 (amended up to Cabinet Order No. 85 of 2025, in force 1 October 2025). PDF 横一段, 38 pages. | https://laws.e-gov.go.jp/data/CabinetOrder/336CO0000000037/624844_1/336CO0000000037_20251001_507CO0000000085_h1.pdf | 453,220 | `d48f7fad61295c2276892e6f308f34462fa1f5abf3182735c7ad708d5bef438e` | PDL1.0 | 2026-10-18T06:52:18Z |
| `regulations/jp_mo_1961_6_fire_service_regulation_r20260626.pdf` | Enforcement Regulation of the Fire Service Act (消防法施行規則, Ordinance of the Ministry of Home Affairs No. 6 of 1961), current version on e-Gov, revision 336M50000008006_20260626_508M60000008081 (amended up to MIC Ordinance No. 81 of 2026, in force 26 June 2026). PDF 横一段, 160 pages. | https://laws.e-gov.go.jp/data/MinisterialOrdinance/336M50000008006/640797_1/336M50000008006_20260626_508M60000008081_h1.pdf | 9,065,099 | `9bbe92e756483e32de8c64eafc5882db3826481c6c674b8e9c507c3a9724251b` | PDL1.0 | 2026-10-18T06:52:28Z |
| `regulations/jp_act_1948_186_fire_service_en_jlt_2008.pdf` | Fire Service Act, Japanese/English reference translation from Japanese Law Translation (Ministry of Justice), reflecting amendments only up to Act No. 41 of 2008 (189 pages, file dated 2022-01-04). No record uses it as `pdfPath`; the Fire Service Act records name it and the page in `version`. | https://www.japaneselawtranslation.go.jp/en/laws/download/3772/14/s23Aa001860401je14.0_h20A41.pdf | 1,295,730 | `2d08229670822d9943026384f3c5bb795e16fc72a2568fd028417ff71969c6bd` | PDL1.0; reference only (verbatim below) | 2026-10-18T06:49:09Z |

Landing pages: the legislation.gov.uk contents pages (`/uksi/2000/128/contents`, `/uksi/1992/3004/contents`, `/ukpga/1974/37/contents`), and the versioned Victorian pages https://www.legislation.vic.gov.au/in-force/statutory-rules/occupational-health-and-safety-regulations-2017/017 and https://www.legislation.vic.gov.au/in-force/statutory-rules/building-regulations-2018/031. The VBA note is also published at https://www.vba.vic.gov.au/__data/assets/pdf_file/0003/136533/Building-ESM-02-Maintenance-of-Essential-Safety-Measures-UNDER-REVIEW-15-Feb-2024.pdf; vba.vic.gov.au now redirects to bpc.vic.gov.au, whose footer reads "Victorian Building Authority, trading as the Building and Plumbing Commission".

Japanese landing pages: the e-Gov law pages https://laws.e-gov.go.jp/law/325AC0100000214, https://laws.e-gov.go.jp/law/323AC1000000186, https://laws.e-gov.go.jp/law/336CO0000000037 and https://laws.e-gov.go.jp/law/336M50000008006. Each PDF link comes from the page's ダウンロード dialog (option "PDF 横一段"). The English page is https://www.japaneselawtranslation.go.jp/en/laws/view/3772.

**Japanese Law Translation has no English translation of the Act on Protection of Cultural Properties.** It lists the Act only as an untranslated title (https://www.japaneselawtranslation.go.jp/en/laws/view/482): the page says the law is not translated and points to e-Gov. A search that included older versions, untranslated titles, tentative translations and outlines found no other entry. The English summaries of the `jp-cpa-*` records are therefore our own reading of the Japanese text. The Enforcement Order and Enforcement Regulation of the Fire Service Act have no translation either, so the same applies to `jp-fso-*` and `jp-fsr-*`.

### California comparison files (US-CA)

Every California file is an HTML snapshot, because these sites publish HTML, not PDF. The leginfo pages sit behind a Cloudflare check, so they were saved from a headless Chrome session; the DIR pages are the files exactly as served.

| Cached file | Instrument and version | Official page | Bytes | SHA-256 | Licence | Retrieved (UTC) |
| --- | --- | --- | ---: | --- | --- | --- |
| `regulations/us_ca_hsc_div13_part2_7.html` | Health and Safety Code, Division 13, Part 2.7 (§§ 18950-18962), as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?lawCode=HSC&division=13.&title=&part=2.7.&chapter=&article= | 154,617 | `d3ee1020288d7df6f1be54deb08a9b53b02e46bba12cbfd32cfb84f59423e6ae` | Public domain (verbatim below) | 2026-10-18T07:17:53Z |
| `regulations/us_ca_lab_6400.html` | Labor Code § 6400, as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=LAB&sectionNum=6400. | 164,615 | `e5b9bb0c37716c85c32b72252b0e94816564e07994f11af903a5dd77f43098ab` | Public domain (verbatim below) | 2026-10-18T07:17:31Z |
| `regulations/us_ca_lab_6401.html` | Labor Code § 6401, as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=LAB&sectionNum=6401. | 163,163 | `1b793a3fbd6cd167ec5bb8d41e8cd38ab0b2aa8838cd7bc4ad5a8ce4c48cfcef` | Public domain (verbatim below) | 2026-10-18T07:17:34Z |
| `regulations/us_ca_lab_div5_part6_ch1.html` | Labor Code, Division 5, Part 6, Chapter 1 (§§ 7620-7626), as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?lawCode=LAB&division=5.&title=&part=6.&chapter=1.&article= | 135,313 | `3f92bff66481091648dff545899355d2f060a03850b5d9af9c21da50aedbf81d` | Public domain (verbatim below) | 2026-10-18T07:18:54Z |
| `regulations/us_ca_lab_div5_part6_ch2.html` | Labor Code, Division 5, Part 6, Chapter 2 (§§ 7650-7655), as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?lawCode=LAB&division=5.&title=&part=6.&chapter=2.&article= | 135,711 | `073f8c3b0dc7c3c5ee7026303226df77ce5677dd24dab604a95b016988ef7a28` | Public domain (verbatim below) | 2026-10-18T07:18:58Z |
| `regulations/us_ca_lab_div5_part6_ch3.html` | Labor Code, Division 5, Part 6, Chapter 3 (§§ 7680-7692), as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?lawCode=LAB&division=5.&title=&part=6.&chapter=3.&article= | 141,167 | `8dc771d9f1943b0b471932dccc61cc60946354cb7561b7d59fbbc11d6dad1848` | Public domain (verbatim below) | 2026-10-18T07:19:01Z |
| `regulations/us_ca_lab_div5_part6_ch5.html` | Labor Code, Division 5, Part 6, Chapter 5 (§ 7750), as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?lawCode=LAB&division=5.&title=&part=6.&chapter=5.&article= | 130,541 | `2791b3c0f0b32915edae6cf83e92e1ea66d9c6fb52e7453d828eed6166c57d74` | Public domain (verbatim below) | 2026-10-18T07:19:05Z |
| `regulations/us_ca_prc_21084_1.html` | Public Resources Code § 21084.1, as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PRC&sectionNum=21084.1. | 163,745 | `4e8e0e668cb05dd0ff36819525aef6bce7e7c75117bcb97533119b737deaa19e` | Public domain (verbatim below) | 2026-10-18T07:17:49Z |
| `regulations/us_ca_prc_5020_1.html` | Public Resources Code § 5020.1, as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PRC&sectionNum=5020.1. | 167,050 | `d9f3eacb7641df990b7ac3ae8ad4d4827c9ed34ab27831b5a79dbcecded055e6` | Public domain (verbatim below) | 2026-10-18T07:17:45Z |
| `regulations/us_ca_prc_5024.html` | Public Resources Code § 5024, as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PRC&sectionNum=5024. | 166,324 | `0f62ef68c8e82f863aca51f749c71d86ef3c4c31e6887fd59c9de69061a5a02d` | Public domain (verbatim below) | 2026-10-18T07:17:38Z |
| `regulations/us_ca_prc_5024_5.html` | Public Resources Code § 5024.5, as displayed on leginfo.legislature.ca.gov (HTML snapshot rendered in a browser) | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PRC&sectionNum=5024.5. | 164,879 | `647898ed4cfef5be861a2a38f027c7a6c0d8827d5745edce6e5a7fcccbccbe07` | Public domain (verbatim below) | 2026-10-18T07:17:42Z |
| `regulations/us_ca_t8_3272.html` | California Code of Regulations, Title 8 § 3272, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/3272.html | 7,340 | `f2eaea0cb2b95557259f6537ba9d2aad064350e1d87cce28e9729168e5c92f67` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:56Z (DIR Date header) |
| `regulations/us_ca_t8_3273.html` | California Code of Regulations, Title 8 § 3273, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/3273.html | 17,915 | `4c2c329af49d1b211880812ed67cdd6923da7692870d2fbb14e650bf7dc59f50` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:56Z (DIR Date header) |
| `regulations/us_ca_t8_3362.html` | California Code of Regulations, Title 8 § 3362, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/3362.html | 7,057 | `368a5780aad264ec71e9931f7842670a7e37721cd6c13f6664daaaab31015713` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:56Z (DIR Date header) |
| `regulations/us_ca_t8_450.html` | California Code of Regulations, Title 8 § 450, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/450.html | 7,452 | `3e72384082688dcf708f9321042b2ddcf34dcb805702df5c63415031d247bafd` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:11Z (DIR Date header) |
| `regulations/us_ca_t8_453.html` | California Code of Regulations, Title 8 § 453, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/453.html | 24,380 | `a17634197dff0558d3e21245ff177b2dd335198d419246988afe4a57e93a4330` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:11Z (DIR Date header) |
| `regulations/us_ca_t8_461.html` | California Code of Regulations, Title 8 § 461, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/461.html | 7,390 | `66988422cc93f42c4330c26f878b0c39b82387208f761828b579d456875c54df` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:11Z (DIR Date header) |
| `regulations/us_ca_t8_462.html` | California Code of Regulations, Title 8 § 462, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/462.html | 34,476 | `0fff7e58bf0eb461548e3ec721a2120696e874e63c8d77bd91f9fcd43fe9814d` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:11Z (DIR Date header) |
| `regulations/us_ca_t8_463.html` | California Code of Regulations, Title 8 § 463, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/463.html | 4,451 | `e2d6c16bf0e38cb0e3a9986a8c968af6ea1b9b60bf47887a529984f2ed131b92` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:11Z (DIR Date header) |
| `regulations/us_ca_t8_465.html` | California Code of Regulations, Title 8 § 465, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/465.html | 8,580 | `c5d4174a191844312b3584a8dd57f93908d03ca8056c4fc161aac54fcb7d4756` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:11Z (DIR Date header) |
| `regulations/us_ca_t8_467.html` | California Code of Regulations, Title 8 § 467, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/467.html | 5,094 | `d7eac176d9161784a2880a1103c0314130dbf5c97c04fdfe9f2117eceda804f2` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:12Z (DIR Date header) |
| `regulations/us_ca_t8_6151.html` | California Code of Regulations, Title 8 § 6151, DIR copy (HTML as served) | https://www.dir.ca.gov/title8/6151.html | 33,350 | `1272f7a6c2fcfdd21cc582a37758b0f66bde2f6093c77e31db8d0a7e0f5174f8` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:12:12Z (DIR Date header) |
| `regulations/us_ca_t8_779.html` | California Code of Regulations, Title 8 § 779 (Boiler and Fired Pressure Vessel Safety Orders), DIR copy (HTML as served) | https://www.dir.ca.gov/title8/779.html | 8,191 | `ec90fbcac9023309eedabd31aa13946b040dbb79e10460f424bc4f7d5c1a5b0b` | Public domain; unofficial copy (verbatim below) | 2026-10-18T07:14:03Z (DIR Date header) |

Link-only sources, which were not cached:
- Title 19 CCR (State Fire Marshal, fire extinguishers) exists officially only in the Barclays Official California Code of Regulations on Westlaw. The sections were read there on 2026-10-18 between 07:23 and 07:25 UTC, with the database current through 10/2/26 Register 2026, No. 40: § 574 https://govt.westlaw.com/calregs/Document/I100760435BE511EC98C8000D3A7C4BC3?viewType=FullText&originationContext=documenttoc&transitionType=CategoryPageItem&contextData=(sc.Default), § 574.1 https://govt.westlaw.com/calregs/Document/I100C1B3D5BE511EC98C8000D3A7C4BC3?viewType=FullText&originationContext=documenttoc&transitionType=CategoryPageItem&contextData=(sc.Default), § 574.5 https://govt.westlaw.com/calregs/Document/I1032DD1A5BE511EC98C8000D3A7C4BC3?viewType=FullText&originationContext=documenttoc&transitionType=CategoryPageItem&contextData=(sc.Default)&bhcp=1, § 575 https://govt.westlaw.com/calregs/Document/I103FD5695BE511EC98C8000D3A7C4BC3?viewType=FullText&originationContext=documenttoc&transitionType=CategoryPageItem&contextData=(sc.Default) and § 575.1 https://govt.westlaw.com/calregs/Document/I1047015C5BE511EC98C8000D3A7C4BC3?viewType=FullText&originationContext=documenttoc&transitionType=CategoryPageItem&contextData=(sc.Default).
- California Historical Building Code (Title 24, Part 8, 2025): https://codes.iccsafe.org/content/CAHBC2025P1. California Fire Code (Title 24, Part 9, 2025): https://codes.iccsafe.org/content/CAFC2025P2. Both links are as listed by the California Building Standards Commission at https://www.dgs.ca.gov/BSC/Codes (retrieved 2026-10-18T07:25:20Z). Nothing was downloaded from either. The Historical Building Code page was opened once only to read its copyright footer, and the Fire Code page was never opened.

## Licence statements

**England (legislation.gov.uk): Open Government Licence v3.0.** The footer of each contents page reads "All content is available under the Open Government Licence v3.0 except where otherwise stated." and links to https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3. This was confirmed on all three pages at 2026-10-18T04:47:50Z. Attribution to show with any served copy: *Contains public sector information licensed under the Open Government Licence v3.0.* Source: legislation.gov.uk.

**Victoria (legislation.vic.gov.au): copyright, personal use only.** The following is verbatim from https://www.legislation.vic.gov.au/copyright (confirmed 2026-10-18T04:47:50Z):

> The information on this website is copyright. No part may be reproduced by any process except in accordance with the provisions of the Copyright Act 1968 of the Commonwealth.
>
> The Government Printer owns copyright in all Victorian legislation and publications printed with the authority of the Government Printer.
>
> Authorised electronic versions are published on this website under section 62 of the Interpretation of Legislation Act 1984 for personal use only. Find out more about authorised versions.
>
> Only the version so published or a printed copy printed directly from that version is an authorised version admissible as evidence thereof before all courts and persons acting judicially within Victoria under section 64 of Interpretation of Legislation Act 1984.
>
> For any copyright enquiries, please contact the Office of the Chief Parliamentary Counsel by email: ocpc@ocpc.vic.gov.au.

Site footer: "© Copyright State Government of Victoria". The site's disclaimer adds that content is provided for information only and that readers should obtain independent advice.

**VBA Practice Note ESM-02.** The following is verbatim from page 6 of the PDF:

> © June 2021 Victorian Building Authority (VBA). This Practice Note has been prepared and published by the VBA for general educational and information purposes only. This publication must not be copied, reproduced, published, adapted, or communicated by any person without the VBA's prior written consent or as permitted by the Copyright Act 1968 (Cth).

The hosting site's statement at https://www.bpc.vic.gov.au/legals/copyright (retrieved 2026-10-18T04:43:55Z) reads:

> You may make limited copies of this website in accordance with the Copyright Act 1968 (Cth), including copies for study, research, criticism, review or news reporting. You may not otherwise reproduce, copy, adapt, modify, communicate, transmit in any form (whether electronic, mechanical or graphic) or otherwise use any part of this website without written permission from the BPC.

**Japan, e-Gov法令検索 (laws.e-gov.go.jp): Public Data License (Version 1.0), PDL1.0.** The following is verbatim from https://laws.e-gov.go.jp/terms (rendered page, retrieved 2026-10-18T06:48:40Z):

> 本サイトの著作権は、特記されていない限りデジタル庁に帰属し、権利表記の記載がない限り「公共データ利用規約（第1.0版）」（PDL1.0）が適用されています。
> PDL1.0 のうち、本サイト独自の出典記載例や本ルールの適用を受けないコンテンツ等サイトによって内容が異なる部分の情報については「コンテンツの利用に係るPDL1.0に関する重要情報」を参照してください。
> 本サイト及び当アカウントのコンテンツの利用に係るPDL1.0に関する重要情報
> 1.1.出典の記載について
> ア
> コンテンツを利用する際は出典を記載してください。出典の記載方法は以下のとおりです。
> （出典記載例）
> 出典：e-Govポータル　（https://www.e-gov.go.jp）
> 出典：「○○意見募集について」（e-Govパブリックコメント） （当該ページのURL）　（○年○月○日に利用）
> 出典：「電子申請API」（e-Gov Developer）（https://developer.e-gov.go.jp/contents/specification/）など
> イ
> コンテンツを編集・加工等して利用する場合は、上記出典とは別に、編集・加工等を行ったことを記載してください。なお、編集・加工した情報を、あたかも国（又は府省等）が作成したかのような態様で公表・利用してはいけません。
> （コンテンツを編集・加工等して利用する場合の記載例）「デザインガイドライン」（e-Gov） （https://www.e-gov.go.jp/about-site/e-gov/designguidelines）をもとに○○株式会社作成　など
> 1.4.本利用規約が適用されないコンテンツについて
> 以下のコンテンツについては、本利用規約の適用外です。
> ア
> 組織や特定の事業を表すシンボルマーク、ロゴ、キャラクターデザイン
> イ
> 具体的かつ合理的な根拠の説明とともに、別の利用ルールの適用を明示しているコンテンツ（別の利用規約の適用を明示しているコンテンツは、本利用規約の別紙に列挙しています。）

PDL1.0 is published by the Digital Agency at https://www.digital.go.jp/resources/open_data/public_data_license_v1.0; the Japanese text is the official one. The following is verbatim from the Japanese text (retrieved 2026-10-18T06:49:10Z):

> 当ウェブサイトで公開している情報（以下「コンテンツ」といいます。）は、別の利用ルールが適用されるコンテンツを除き、どなたでも以下の1.1.から1.7.に定める利用ルール（以下「本利用ルール」といいます。）に従って、複製、公衆送信、翻訳・変形等の翻案等、自由に利用できます（本利用ルールに従って利用できるコンテンツを、以下「本コンテンツ」といいます。）。商用利用も可能です。本コンテンツの利用に当たっては、本利用ルールに同意したものとみなします。
>
> 本利用ルールは、クリエイティブ・コモンズ・ライセンスの表示4.0 国際ライセンスに規定される著作権利用許諾条件（以下「CC BY」といいます。）と互換性があります。国（本コンテンツが国ではなく地方公共団体によって提供されている場合はその地方公共団体）は、本利用ルールが適用される本コンテンツについて、利用者がCC BYに従って利用することを許諾します。

The following is verbatim from the English reference version at https://www.digital.go.jp/en/resources/open_data/public_data_license_v1.0 (retrieved 2026-10-18T06:49:33Z), which states that it is for reference only:

> Information made available on this website (hereinafter referred to as Content), except for Content subject to other terms of use, may be freely used, copied, publicly transmitted, translated or otherwise modified on condition that the user complies with provisions 1.1 to 1.7 below (hereinafter referred to as “This Terms of Use”). Content that can be used in accordance with “This Terms of Use” is hereinafter referred to as "This Content". Commercial use of “This Content” is also permitted. Use of “This Content” constitutes agreement by the user with “This Terms of Use”.
>
> The user must cite the source when using “This Content”. Sources should be cited in the following manner for how to cite the sources, such as by replacing the name of the information provider and its URL. If the URL link can be used as a source, the user can also add the link to the relevant text in the parentheses. In addition, if examples of source citations are provided in "Important note on Public Data License (Version 1.0)" related to “This Content”, please refer to those examples instead of the examples below.
>
> If the user has edited “This Content” for use, you must include a statement expressing that “This Content” has been edited and the name of entity, in addition to the abovementioned source citation. Besides, if examples of source citations are provided in "Important note on Public Data License (Version 1.0)" related to “This Content”, sources should be cited in those manner instead of the examples below. But not in any way making public or using edited information in a format that may be misconstrued as if national government or the relevant ministries (This also applies if “This Content” is provided by the local government) has just created and unedited by anyone else.
>
> “This Terms of Use” is compatible with the Creative Commons Attribution License 4.0 (hereinafter referred to as the CC BY).National government (If “This Content” is provided by a public institution such as a local government instead of the national government, the public institution such as the local government) permits the user to use “This Content” to which “This Terms of Use” apply in accordance with CC BY.

Attribution to show with any served e-Gov copy (the `licence` field of each JP record ends with it, filled in for its law): *出典：「法令名」（e-Gov法令検索）（law page URL）、PDL1.0（https://www.digital.go.jp/resources/open_data/public_data_license_v1.0）（2026年10月18日に利用）*. In English: Source: e-Gov Law Search (Digital Agency, Japan), PDL1.0. Because PDL1.0 and the e-Gov terms require edited content to say so and not to look government-made, show next to it that the summaries are our own wording, not the government's.

**Japanese Law Translation (japaneselawtranslation.go.jp): PDL1.0, translations for reference only.** The following is verbatim from https://www.japaneselawtranslation.go.jp/en/index/terms (retrieved 2026-10-18T06:49:10Z):

> Information published on this site (referred to below as "content") is subject to the "Public Data License (Version 1.0)" (PDL1.0) unless stated otherwise. In addition, the copyright belongs to the Ministry of Justice of Japan unless stated otherwise.
>
> The translations contained in the Japanese Law Translation Database System are not official texts, and not all of the translations are finalized versions. Only the original Japanese texts of the laws and regulations have legal effect, and the translations are to be used solely as reference materials to aid in the understanding of Japanese laws and regulations. The government of Japan is not responsible for the accuracy, reliability or currency of the legislative material provided in this website, or for any consequence resulting from use of the information in this website. For all purposes of interpreting and applying law to any legal issue or dispute, users should consult the original Japanese texts published in the Official Gazette. Translation of laws and regulations is carried out in accordance with the plan (Translation Development Plan) decided by the "Liaison Conference of Relevant Ministries and Agencies on the Development of Infrastructure for Promoting Translation of Laws and Regulations into Foreign Languages".
>
> The data contained in the Japanese Law Translation Database System may be cited, reproduced, or reprinted in accordance with the Terms of Use.

Attribution for the English file: *Source: Japanese Law Translation Database System (Ministry of Justice, Japan), Fire Service Act, https://www.japaneselawtranslation.go.jp/en/laws/view/3772, PDL1.0. Reference translation, not an official text.*

**California, leginfo.legislature.ca.gov (statutes): public domain.** The following is verbatim from the notice on https://leginfo.legislature.ca.gov/faces/home.xhtml (retrieved 2026-10-18T07:17:57Z):

> Pursuant to Section 10248.5 of the Government Code, the information described in subdivision (a) of Section 10248 of the Government Code and made available on this Web site is within the public domain and the State of California retains no copyright or other proprietary interest in the information.

**California, dir.ca.gov (Title 8 regulations): public domain, unofficial copy.** Each Title 8 page carries this banner, verbatim:

> This information is provided free of charge by the Department of Industrial Relations from its web site at www.dir.ca.gov. These regulations are for the convenience of the user and no representation or warranty is made that the information is current or accurate. See full disclaimer at https://www.dir.ca.gov/od_pub/disclaimer.html.

The following is verbatim from the DIR disclaimer (https://www.dir.ca.gov/od_pub/disclaimer.html, dated 8/2/2013):

> Users should not rely on the statutes (laws) and regulations posted on this website as definitive but should consult the following sources: ... To access the official California regulations, visit the website of the California Office of Administrative Law, and select California Code of Regulations.

The following is verbatim from the DIR conditions of use (https://www.dir.ca.gov/od_pub/conditions.html):

> In general, information presented on this web site, unless otherwise indicated, is considered in the public domain. It may be distributed or copied as permitted by law. However, the State does make use of copyrighted data (e.g., photographs) which may require additional permissions prior to your use.

**California, Title 19 on govt.westlaw.com: official CCR, link only.** The following is verbatim from OAL (https://oal.ca.gov/publications/ccr/):

> OAL contracts with Barclays, a division of Thomson-Reuters to provide a free online version of the Official CCR.

The following is verbatim from the CCR site (https://govt.westlaw.com/calregs/Index):

> This website is maintained by Thomson Reuters. By using this website, you agree not to use it in any manner that could disable, overburden, damage, or impair the site or interfere with any other party’s use of the website, or to use any device, software or routine that interferes with the proper working of the website.

No permission to copy or redistribute is stated, so the Title 19 records carry `servePdf: false` and `pdfPath: null`.

**California, ICC-published Title 24 codes: link only.** The following is verbatim from the code site's footer (codes.iccsafe.org):

> COPYRIGHT © 2026 INTERNATIONAL CODE COUNCIL, INC. ALL RIGHTS RESERVED.

The following is verbatim from the CCR help page (https://govt.westlaw.com/calregs/Help):

> Title 24 of the California Code of Regulations, known as California Building Standards, contains copyrighted materials under the ownership of several model code publishers and cannot be provided here.

Each US-CA record's `licence` ends with an `Attribution:` sentence, which the backend shows with any served copy.

## Serving the PDFs (`servePdf`)

- `servePdf: true` (the three OGL files): `GET /api/regulations/{id}/file` may stream the cached PDF, with the OGL attribution line above in a response header and in the UI.
- `servePdf: true` (the four e-Gov files, Japan): PDL1.0 allows copying and public transmission, commercial use included, if the source is cited. Stream them unmodified with the e-Gov attribution above (in a response header and in the UI), plus the note that the summaries are ours. The Japanese Law Translation file may be served the same way with its own attribution. Note for the backend: `backend/src/regulations.py` currently returns the OGL attribution for every served file, so JP records need the PDL1.0 line instead.
- California: `servePdf: true` for the leginfo and DIR snapshots, which are public domain. The backend streams only `.pdf` files, so for these HTML snapshots it currently redirects to `pdfUrl`, the official page. `servePdf: false` with `pdfPath: null` for Title 19 (Westlaw) and for the two ICC codes, which are links only.
- `servePdf: false` (the Victorian legislation and the VBA note): neither licence permits redistribution. The local copy is for the operator's own reading only. For anyone else, the endpoint should redirect (302) to `pdfUrl`, and the UI should link to `pdfUrl` or `officialUrl`.

## Record fields

Contract §5 fields: `id`, `jurisdiction` (`ENG-UK` | `VIC-AU` | `JP` | `US-CA`), `instrument`, `provision`, `title` (the provision's heading), `officialUrl`, `pdfPath`, `licence`, `retrievedAt`, `summary` (1 to 3 sentences in our own words, with no direct quotations), `appliesTo` (scenario ids and issue kinds) and `pageHint`.

The other fields are additive and can be ignored by consumers that do not need them:

- `siteIds`: `bristol-pumps` for ENG-UK records, `myer-plant` for VIC-AU records and `tomioka-mill` for JP records, for `GET /api/regulations?siteId=`. No JP record lists `bristol-pumps`, because Japanese law does not bind the Bristol site.
- `binding` and `comparisonFor` (US-CA records only): `binding: false` marks a comparison record, and `comparisonFor` lists the sites whose scenarios it is compared with. `siteIds` repeats the same list so the loader can find them. The backend (`backend/src/regulations.py`) lists these records only with `include=comparison` and never cites them as the reason an issue is a breach. US-CA `pageHint` is null because the snapshots are HTML.
- `sourceType`: `legislation`, or `guidance` (the VBA note, which is not law).
- `pdfUrl`: the exact official PDF fetched. For UK records, `officialUrl` is the provision's own web page; for Victorian records it is the versioned landing page, because that site has no per-provision pages. For Japanese records it is the e-Gov law page with the article's anchor (for example `#Mp-Ch_3-Se_1-Ss_3-At_43`). That page always shows the current version, and `version` names the revision cached.
- `version`, `licenceUrl` and `servePdf`, described above.
- `synthetic: false`: the sources are real, unlike the scenarios that cite them.

`pageHint` is the 1-based physical page of the cached PDF, so it works as `#page=N` in a PDF viewer. In the Victorian PDFs, body page numbers printed on the page differ: in the OHS Regulations the printed number is the PDF page minus 24, and in the Building Regulations it is the PDF page minus 16. In the UK PDFs and the e-Gov PDFs the printed and physical page numbers match.

## Scenario mapping

| Scenario | Site | Regulation ids |
| --- | --- | --- |
| `br-sump` (sump at 96 % and rising towards the visitor walkway) | bristol-pumps | `eng-whswr-1992-reg-12`, `eng-whswr-1992-reg-5`, `eng-hswa-1974-s-3`, `eng-hswa-1974-s-2` |
| `br-vessel-cert` (PV-301 examination date passed, steam demonstration blocked) | bristol-pumps | `eng-pssr-2000-reg-9-6`, `eng-pssr-2000-reg-9`, `eng-pssr-2000-reg-8`, `eng-pssr-2000-reg-14`, `eng-pssr-2000-reg-2`, `eng-hswa-1974-s-3`, `eng-hswa-1974-s-2` |
| `my-overpressure` (PG-601 at 4.1 bar on a 3.5 bar circuit) | myer-plant | `vic-ohsr-2017-reg-98`, `vic-ohsr-2017-reg-97`, `vic-ohsr-2017-reg-121`, `vic-ohsr-2017-reg-105`, `vic-ohsr-2017-reg-106`, `vic-ohsr-2017-reg-18`, `vic-ohsr-2017-reg-74` |
| `my-extinguisher` (FE-1001 routine inspection 9 days overdue) | myer-plant | `vic-br-2018-reg-195`, `vic-br-2018-reg-216`, `vic-br-2018-sch-8`, `vic-br-2018-reg-226`, `vic-br-2018-reg-225`, `vic-br-2018-reg-223`, `vic-vba-pn-esm-02` |
| `x-maintenance` (Bristol asks Myer about an examiner and a written-scheme template) | both | Bristol: `eng-pssr-2000-reg-8`, `eng-pssr-2000-reg-9`, `eng-pssr-2000-reg-2`, `eng-pssr-2000-reg-14`, `eng-hswa-1974-s-4`. Myer: `vic-ohsr-2017-reg-105`, `vic-ohsr-2017-reg-106`, `vic-ohsr-2017-reg-74` |
| `tm-humidity` (88 % humidity after a typhoon threatens the Silk Reeling Mill's trusses and reeling machines) | tomioka-mill | `jp-cpa-1950-art-31`, `jp-cpa-1950-art-119`, `jp-cpa-1950-art-36`, `jp-cpa-1950-art-33`, `jp-cpa-1950-art-4` |
| `tm-alteration-permit` (a contractor proposes drilling brackets into the National Treasure brick wall BW-251) | tomioka-mill | `jp-cpa-1950-art-43`, `jp-cpa-1950-art-125`, `jp-cpa-1950-art-197`, `jp-cpa-1950-art-184`, `jp-cpa-1950-art-53-4` |
| Fire-safety duty, no scenario id (periodic inspection and report for the extinguishers FE-501 to FE-503 and the hydrant FH-601; issue kind `inspection_overdue`) | tomioka-mill | `jp-fsa-1948-art-17-3-3`, `jp-fsr-1961-art-31-6`, `jp-fsa-1948-art-17`, `jp-fso-1961-art-6`, `jp-fso-1961-art-10`, `jp-fso-1961-art-36`, `jp-fsa-1948-art-17-4`, `jp-fsa-1948-art-8` |
| `x-heritage` (Tomioka asks Bristol about heritage-safe sensor mounting and visitor-route closure) | both | Tomioka: `jp-cpa-1950-art-43`, `jp-cpa-1950-art-125`, `jp-cpa-1950-art-4`, `jp-cpa-1950-art-119`, `jp-fsa-1948-art-8`. Bristol: `eng-whswr-1992-reg-12`, `eng-hswa-1974-s-3`, cited only through `obl-x-heritage-bristol` |
| California comparison for `br-sump` | bristol-pumps | `us-ca-t8-3273`, `us-ca-t8-3272`, `us-ca-t8-3362`, `us-ca-lab-6400` (`obl-ca-br-sump`) |
| California comparison for `br-vessel-cert` | bristol-pumps | `us-ca-t8-467`, `us-ca-lab-7680`, `us-ca-t8-461`, `us-ca-t8-462`, `us-ca-lab-7650` (`obl-ca-br-vessel-cert`) |
| California comparison for `my-overpressure` | myer-plant | `us-ca-t8-467`, `us-ca-t8-465`, `us-ca-lab-7687` (`obl-ca-my-overpressure`) |
| California comparison for `my-extinguisher` | myer-plant | `us-ca-t8-6151`, `us-ca-t19-574-1`, `us-ca-t19-575-1`, `us-ca-cfc-2025` (`obl-ca-my-extinguisher`) |
| California comparison for `x-maintenance` | both | `us-ca-lab-7650`, `us-ca-t8-779`, `us-ca-t8-462` (`obl-ca-x-maintenance-bristol`, `obl-ca-x-maintenance-myer`) |
| California comparison for `tm-humidity` | tomioka-mill | `us-ca-prc-5024`, `us-ca-hsc-18954`, `us-ca-chbc-2025`, `us-ca-t8-3362` (`obl-ca-tm-humidity`) |
| California comparison for `tm-alteration-permit` | tomioka-mill | `us-ca-prc-5024-5`, `us-ca-prc-5024`, `us-ca-prc-21084-1`, `us-ca-hsc-18954`, `us-ca-chbc-2025` (`obl-ca-tm-alteration-permit`) |
| California comparison for the Tomioka fire-safety duty (`inspection_overdue`) | tomioka-mill | `us-ca-t19-574-1`, `us-ca-t19-575-1`, `us-ca-t8-6151`, `us-ca-cfc-2025` (`obl-ca-tm-fire-equipment`) |

Issue kinds used in `appliesTo`: `sump_overflow`, `walkway_closure`, `certificate_expired`, `overpressure`, `inspection_overdue`, `humidity_high`, `alteration_permit` and `visitor_route`. Filter by `siteIds` as well: records cover `inspection_overdue` at Myer (Victorian law) and at Tomioka (Japanese law), but none cover it at Bristol.

## Caveats found while reading the sources

- **Victoria has no written-scheme rule.** Version 017 of the OHS Regulations 2017 contains neither "written scheme" nor "scheme of examination". Myer's duties are to inspect plant as far as needed to monitor its risk (reg 105) and to keep records (reg 106). A template from Myer can inform PV-301's scheme, but under PSSR reg 8 that scheme must be drawn up or certified as suitable for PV-301 by a competent person.
- **Hazard levels decide scope in Victoria.** Part 3.5 covers pressure vessels and piping only at AS 4343 hazard levels A to D, and reg 106 records only at levels A to C for vessels. The hazard levels of the synthetic Myer assets are not known, so the records say "where".
- **Australian Standards were not consulted.** AS 4343 and AS 1851 are paid Standards Australia publications. Inspection frequencies come from each building's occupancy permit, maintenance determination or maintenance schedule (Building Regulations regs 194, 195, 216 and 222), not from this pack.
- **There is no Victorian pressure-equipment guidance PDF here.** WorkSafe Victoria's current pressure-vessel guidance is a web page (https://www.worksafe.vic.gov.au/air-receiver-pressure-vessels), and the PDF version is archived. Neither is included.
- **HSWA dates differ.** The revised HSWA PDF says it is up to date with changes in force on or before 24 July 2026, when it was generated, while the web page said 18 October 2026 on retrieval. HSWA also has changes that may come into force later.
- **Error in the synthetic seed (another stream's file).** `backend/seed/synthetic/obligations.json` cites "Occupational Health and Safety Regulations 2017, Part 5.1" for plant. In Version 017, Part 5.1 is Construction and Plant is Part 3.5 (regs 74 to 127C). The same file's `ob-my-tk201-scheme` uses the UK "written scheme of examination" wording for a Victorian vessel.

- **Japan: no English text for most of the Japanese law in this pack.** Only the Fire Service Act has a Japanese Law Translation version (see the landing-page note above). Every other English summary is our own reading of the Japanese text.
- **Japan: the Fire Service Act translation is out of date.** It reflects amendments only up to Act No. 41 of 2008. Its penalty wording ("imprisonment with work") predates the 拘禁刑 (imprisonment) wording the current Japanese text has used since 1 June 2025. The article numbers of the cited provisions match the current Act. Read the Japanese PDF for the current text.
- **Japan: the indoor hydrant FH-601 may not be required equipment.** Enforcement Order 第11条 does not list item (17) buildings by floor area, so this pack does not show that FH-601 is required. Another use of the building, or a municipal ordinance under Fire Service Act 第17条第2項, could require it; neither was checked.
- **Japan: inspection intervals are set in an FDMA notice.** Regulation 第31条の6第1項 leaves the intervals (at most one year) to the Commissioner of the Fire and Disaster Management Agency. That notice is not on e-Gov and is not in this pack.
- **Japan: who grants the permit.** 第184条 lets a Cabinet Order delegate permits for non-major alterations to a prefectural or city board of education. The Enforcement Order of the Cultural Properties Act (文化財保護法施行令) was not downloaded, so the authority for BW-251 is not confirmed.
- **Japan: owner or management body.** Whether a management body (管理団体) has been designated for the mill was not checked. The records describe both cases.
- **Japan: the reeling machines.** Whether RM-101 to RM-106 are themselves designated was not checked. The management duty in 第31条 attaches to the designated buildings, whose roof trusses are at risk.
- **Japan: site designation (context only, not a record source).** Gunma Prefecture (https://www.pref.gunma.jp/page/5167.html, retrieved 2026-10-18T06:59:55Z) lists three designations. The National Treasures are 繰糸所, 東置繭所 and 西置繭所 (notice of 10 December 2014). The Important Cultural Properties are 蒸気窯所, 鉄水溜, 下水竇及び外竇, 首長館, 女工館 and 検査人館 (5 July 2006). The Historic Site is 敷地全体, the whole site (14 July 2005). 文化遺産オンライン (https://online.bunka.go.jp/heritages/detail/158535) gives the East Cocoon Warehouse the same dates and describes the Silk Reeling Mill's king-post truss roof.
- **Japan: e-Gov PDF dates.** The PDFs of the two Acts and the Enforcement Order were generated before their revisions came into force (2025-02-17, 2024-07-22 and 2025-04-08), because e-Gov prepares the text in advance. Every cited sentence matches the official XML of the same revision. The only difference found is the ヽ iteration mark in き損, which is drawn as ruby and extracts out of order. Both Acts use 拘禁刑 throughout, as the 1 June 2025 revision does.
- **Japan: not added.** The Industrial Safety and Health Act was left out because no Tomioka scenario needs worker-safety duties. UK listed-building consent rules for Bristol's historic fabric, relevant to `x-heritage`, are not in this pack either.
- **Japan: proposed ids.** The Tomioka suggested obligations name seed obligation ids (`ob-tm-*`) and crew ids (`crew-tm-fire-officer`, `crew-tm-visitor-safety-lead`) that did not exist yet. Only `crew-tm-conservation-architect` and `crew-tm-conservator` were already in the frontend. The seed and crew streams should use these ids, or the entries should be edited.

- **California: comparison only.** None of the sites is in California. The US-CA records describe what would apply if a site were there, so they are never the reason anything is a breach.
- **California: pressure vessel classes.** Labor Code Part 6 ("Tanks and Boilers", §§ 7620-7771) covers only tanks (unfired vessels storing air or LP-gas) and boilers (vessels generating steam). Title 8 limits its permit and inspection regime to air and LP-gas tanks (§ 450(a)(4)). Neither PV-301 (a steam receiver) nor TK-201 was classified here, and of the Boiler and Fired Pressure Vessel Safety Orders only § 779 was read. A steam receiver could fall under rules this pack does not contain.
- **California: employees, not visitors.** Labor Code §§ 6400 and 6401 and the Title 8 orders protect employees. No California rule protecting visitors on the walkway was found or added; premises-liability law is out of scope.
- **California: state-owned historic property only.** Public Resources Code §§ 5024 and 5024.5 bind state agencies for state-owned resources. Local landmark ordinances and permits were not checked, and neither were the projects the environmental review division (§ 21084.1) reaches. No section of the Historical Building Code itself was read or cited (ICC copyright).
- **California: Title 8 copies are unofficial.** DIR says its pages are a convenience copy and that the official text is the CCR (Barclays, on Westlaw). The Title 8 sections were checked against DIR's copy only, not against Westlaw.
- **California: Title 19 and the Fire Code are not cached.** Title 19 was read on Westlaw; scratch copies were kept for checking, outside the repo. The California Fire Code was neither opened nor cited, so which extinguishers it would require at each site is not known.
- **California: retrieval clocks.** DIR's server clock ran about six minutes behind the local clock, which matched e-Gov's server. DIR retrieval times are taken from DIR's `Date` headers; all other times come from the local clock.

## Refreshing the cache

1. **legislation.gov.uk:** the revised PDFs (`.../data.pdf`) are generated on demand behind an AWS WAF JavaScript challenge, so plain `curl` gets HTTP 202 with an empty body. Open the URL in a real browser (a headless Chrome session works) and save the PDF. The as-made King's Printer PDFs are plain downloads, but they are not the revised text: https://www.legislation.gov.uk/uksi/2000/128/pdfs/uksi_20000128_en.pdf and https://www.legislation.gov.uk/ukpga/1974/37/pdfs/ukpga_19740037_en.pdf (none exists for SI 1992/3004).
2. **legislation.vic.gov.au:** check the "Version history" on the instrument's in-force page for a newer authorised version, then download its PDF directly. These downloads can reset mid-transfer; resume them and compare the size with `Content-Length`.
3. **bpc.vic.gov.au:** this site sits behind a Cloudflare challenge, so use a browser.
4. **laws.e-gov.go.jp:** check for a newer revision with the API, `https://laws.e-gov.go.jp/api/2/law_revisions/{lawId}` (law ids 325AC0100000214, 323AC1000000186, 336CO0000000037 and 336M50000008006), and watch for any `UnEnforced` revision. The PDF links come from the law page's ダウンロード dialog, which the page loads with script, so open it in a browser or headless Chrome. The files themselves are plain downloads under `https://laws.e-gov.go.jp/data/...`, and curl works on them. The API serves XML, JSON, HTML, RTF and DOCX but not PDF: `/api/2/law_file/pdf/...` answers 400.
5. **japaneselawtranslation.go.jp:** plain curl works; the search form is a POST with a CSRF token. Check /en/laws/view/3772 for a newer Fire Service Act translation, and /en/laws/view/482 in case the Cultural Properties Act is translated.
6. **leginfo.legislature.ca.gov:** pages sit behind a Cloudflare check, so open them in headless Chrome and save the rendered HTML. Part-level `codes_displayText` pages show only a contents list; open each chapter instead.
7. **dir.ca.gov (Title 8):** plain curl works. **govt.westlaw.com (Title 19):** browse in headless Chrome (Title 19 → Division 1 → Chapter 3 → Article 6) and do not cache. **ICC codes:** link only.
8. **After any refresh:** update the hashes, versions and `retrievedAt` values, and re-check every `pageHint`, because page numbers move between versions.
