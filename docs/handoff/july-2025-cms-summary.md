# CMS July 2025 hospital star ratings validation summary

**Draft for Abt review before sharing with CMS**

Input release: July 2025 Overall Hospital Quality Star Rating SAS package

Replay date: November 16, 2026

The project team reproduced the July 2025 hospital star-rating results in Python. The replay processed **4,566 hospitals**, of which **2,891 were eligible for a rating**. All **ten outputs** matched the supplied SAS references under the configured comparison rules. Every individual star assignment matched exactly, and national average scores matched within the numerical tolerance.

| Star rating | Hospitals |
|---|---:|
| 1 star | 233 |
| 2 stars | 661 |
| 3 stars | 939 |
| 4 stars | 767 |
| 5 stars | 291 |
| Total rated | 2,891 |
| Unrated | 1,675 |

The replay covered measure standardization, domain scoring, eligibility, star assignment and national averages. It used a mix of model-generated Python and human-written code, including a manual correction to the clustering step. Abt can use the technical report to check the run details and review which results are appropriate to share.

This validation covers the supplied July 2025 release. The independent teammate replay and Abt review are pending. **Hospital-level results file:** pending Abt approval.
