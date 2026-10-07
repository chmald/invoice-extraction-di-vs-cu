# Changelog

## Unreleased (2026-10-07): repository renamed to `invoice-extraction-di-vs-cu`

- GitHub repository renamed from `azure-di-vs-cu` to `invoice-extraction-di-vs-cu` to name the use case (invoice extraction across changing vendor layouts). Old links redirect automatically.
- README title, `azure.yaml` project name/template metadata, and diagram footers updated to the new name; diagram PNGs re-exported. No code, Azure resource, or environment names changed.

## 1.1.0 (2026-10-07): validated against current Microsoft Learn, retrofitted to the demo standard, published as `azure-di-vs-cu`

### Corrected (verified against Microsoft Learn on 2026-10-07)

| Was | Now | Why |
|---|---|---|
| CU analyze posted raw bytes to `:analyze` | `:analyzeBinary` for bytes (`:analyze` takes `{"inputs":[{"url":…}]}`) | The `2025-11-01` GA API changed the analyze contract ([migration guide](https://learn.microsoft.com/azure/ai-services/content-understanding/how-to/migration-preview-to-ga)) |
| Analyzer `baseAnalyzerId: prebuilt-documentAnalyzer`, no `models` block | `prebuilt-document` + `models: {completion, embedding}` | GA base analyzers are `prebuilt-document/-audio/-video/-image`; custom analyzers name their generative models |
| No resource defaults, no model deployments | `setup` PATCHes `contentunderstanding/defaults`; Bicep deploys `gpt-5.2` (2025-12-11) + `text-embedding-3-large` | GA custom analyzers need model deployments mapped in the resource defaults |
| `fieldSchema.descriptions` | `fieldSchema.description`; `method` removed from array/object item definitions | Matches the GA analyzer reference |
| DI mapped a top-level `CurrencyCode` field | Read from `valueCurrency.currencyCode` on the amount fields | `prebuilt-invoice` v4.0 has no top-level currency field |
| "CU reports confidence selectively; generate/classify fields have none" | Confidence + grounding for extract, generate and classify fields when `estimateFieldSourceAndConfidence` is on | July 2026 update; fixtures now carry confidences for CU inferred fields |
| "CU 1.0 / CU 2.0", "semantic chunking", "PRO mode" | API `2025-11-01` (GA) / `2026-06-01-preview` (agentic mode, synchronous Read/Layout, signatures, classification enhancements) | Matches Learn naming and the current feature list |
| "Azure AI Document Intelligence / Content Understanding" | "Azure Document Intelligence / Content Understanding in Foundry Tools", on a Microsoft Foundry (AIServices) resource | Current product naming |
| No CU region list | 12 CU regions enforced by the preprovision hook | [Region support](https://learn.microsoft.com/azure/ai-services/content-understanding/language-region-support) |

Still valid: DI v4.0 `2024-11-30` GA and the `azure-ai-documentintelligence` 1.0.x SDK; prebuilt-invoice fields used by the harness; CU `2025-11-01` as the GA production target; `result.contents[0].fields` response path; FormRecognizer and AIServices ARM kinds. The CU Python SDK `azure-ai-contentunderstanding` is GA (1.1.0) and is mentioned as the production choice; the harness keeps REST for visibility.

### Added

- One-command `azd up`: `azure.yaml`, subscription-scoped `infra/azd.bicep`, quoted `infra/azd.parameters.json`, `infra/hooks/{preprovision,postprovision,common}.ps1` (env-name, CU-region and **tenant/subscription guard**, soft-delete check, writes `demo-ids.local.json`), and `infra/deploy.ps1` sharing the same helpers.
- `infra/main.bicep`: model deployments, optional dedicated DI account, optional `Cognitive Services User` assignment, `disableLocalAuth` switch.
- Configurable workload block (`diModelId`, `contentUnderstandingAnalyzerId`, `cuAnalyzerSchema`, `criticalFields`) so retargeting is configuration, not code.
- Offline test suite: harness behavior, GA REST contract (fake session), reusability + publish-safety guards, configuration-reference guard, doc-visuals lint.
- Docs rebuilt on the visual standard: 13 draw.io diagrams with official Azure icons + PNG exports, local icons and badges, `docs/03b-manual-deployment.md`, `docs/08-configuration-reference.md`.

### Removed

- Engagement-specific names, internal-only sourcing notes and real-looking addresses from code, fixtures and docs; generic Contoso / Northwind / Fabrikam fixtures instead.

## 1.0.0 (2026-08-18)

- Initial comparison harness: DI vs. CU extraction, normalized result model, scorecard with totals reconciliation, tiered DI → CU → OCR router, migration assessment, offline `simulate` fixtures, Bicep for both services, decision guide and use-case chart.
