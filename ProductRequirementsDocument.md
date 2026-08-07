# Personal Digital Filing Cabinet (Life Cabinet)

## Product Requirements Document (PRD)

### Version
v1.0

---

# 1. Vision

Life Cabinet is an AI-powered personal document management system that serves as a digital filing cabinet for an individual's entire life.

Unlike cloud storage services that primarily organize files by folders, Life Cabinet organizes documents around real-world entities such as properties, vehicles, family members, finances, insurance policies, and travel, while providing intelligent search, document workflows, reminders, and AI assistance.

The system should feel like having a personal executive assistant that always knows where every important document is.

---

# 2. Goals

The application should enable users to:

- Store every important personal document
- Find any document within seconds
- Never lose track of important deadlines
- Organize documents naturally around life events
- Scan and classify documents automatically
- Keep everything synchronized across devices
- Use AI to understand and summarize documents
- Reduce manual organization effort

---

# 3. Target Users

### Primary

Individuals managing personal life documents.

Examples:

- Home owners
- Families
- Professionals
- Freelancers
- Expats
- Frequent travelers

---

### Secondary

Small family groups sharing documents.

Examples

- Husband and wife
- Parents and children
- Elder care
- Financial advisors

---

# 4. Core Principles

## Organize by life—not folders.

Users think:

> "This belongs to my BMW"

not

> "This belongs in Folder A/B/C"

---

## One document. Multiple views.

Every document exists only once.

It can appear in:

- Vehicle
- Finance
- Search
- Timeline
- Recently Viewed

without duplication.

---

## AI-first

The application should automatically:

- Read documents
- Extract metadata
- Classify documents
- Detect expiration dates
- Suggest categories
- Link related documents

---

## Search-first

Users should rarely browse folders.

Search should retrieve documents by:

- keywords
- OCR text
- people
- property
- company
- document type
- amount
- date
- tags
- AI understanding

---

# 5. Information Architecture

## Main Navigation

```
Home

Workflow

Cabinet

Search

Activity

Settings
```

---

# Cabinet

```
Identity & Legal

Finance

Property

Vehicles

Insurance

Health

Family

Career & Business

Education

Travel

Purchases & Warranties

Reference

Archive
```

---

# Workflow

```
Inbox

Needs Action

Waiting

Completed
```

Workflow status is independent from cabinet location.

---

# 6. Dashboard

The Home dashboard displays:

## Needs Attention

- Documents awaiting action
- Policies expiring soon
- Bills due
- Missing information

---

## Recent Documents

Recently scanned

Recently uploaded

Recently modified

---

## Upcoming

Upcoming renewals

Passport expiration

Insurance renewal

Visa expiry

Vehicle inspection

Tax deadlines

---

## Quick Access

Favorite documents

Frequently accessed

Pinned folders

---

## Search

Persistent global search bar.

---

# 7. Cabinet Structure (Classification Taxonomy)

Documents are classified along a hierarchical taxonomy: **Domain → Subdomain → Class → Subclass**. Subdomain and Subclass levels are used only where they earn their keep — not every branch needs all four levels.

The taxonomy is curated, not fully closed. Predefined branches cover the common cases; when a document doesn't fit any existing leaf well, AI proposes a new one for review instead of forcing a bad match or silently inventing a category (see Section 14, Auto Classification).

Classes such as Contract, Invoice, Insurance Policy, and Statement recur across multiple domains. They are defined once — including their metadata fields (Section 11) — and reused wherever they apply, rather than redefined per domain.

Example

```
Property

    Real Estate

        Purchase / Sale Contract

        Mortgage

        Deed / Title

        Utility Account

    Rental

        Lease Agreement

        Rent Receipt

Vehicles

    Registration

    Insurance

    Service & Repairs

    Purchase / Loan

Career & Business

    Employment

        Employment Contract

        Payslip

        Performance Review

    Business Operations

        Formation & Licensing

            Registration Certificate

            Business License

        Contracts

            Client Contract

            Vendor Contract / NDA

        Payroll & HR

            Employee Contract

            Payroll Report

        Business Banking

            Business Bank Statement

            Invoice (Issued / Received)

Health

    Records

        Visit Summary

        Lab Result

    Insurance Claims

    Prescriptions
```

Personal, family, and small-business documents share this same taxonomy — the "Business Operations" subdomain above exists because those document classes (payroll, business licensing) don't apply to personal life, not because business documents get a separate tree. Whose document it is — personal, a specific family member's, or a specific business's — is handled orthogonally, as ownership context rather than classification. See Section 8.

---

# 8. Context & Parties

Every document belongs to one or more **Parties** — the person or entity it concerns. A Party has one of three types:

```
self             the account holder

family_member    a specific family member (spouse, child, parent, ...)

business         a specific small business the account holder owns
```

A document's **context** — Personal, Family, or Business — is derived from the type of its Party, not maintained as a separate field, so it can never drift out of sync with who the document actually belongs to.

A document can carry more than one Party. Example: a vehicle used both personally and for a registered small business links to both a `self`/`family_member` Party and a `business` Party, and surfaces under both contexts.

```
users/{account}/parties/{id}

    name

    type       self | family_member | business

    meta       relation, date of birth        (family_member)
               entity type, registration no.  (business)
```

Assets may declare a default Party (e.g. a "Business Checking Account" asset defaults to the business Party); documents filed under that asset inherit it but can override per document.

## Cabinet Context Switcher

```
All | Personal | Family ▾ | Business ▾
```

Family and Business expand to list individual members/entities once more than one exists. Selecting a context scopes both the taxonomy tree (Section 7) and search (Section 12) to documents whose Party list includes it.

This registry is also the foundation for family sharing (Section 19, Section 24): inviting a family member's own login and linking it to their Party record scopes their view to their own documents.

---

# 9. Document Model

Each document contains:

```
UUID

Title

Original filename

Description

Taxonomy Path (Domain / Subdomain / Class / Subclass)

Asset

Owner

Parties (context: personal / family / business — one or more)

Workflow Status

Document Date

Upload Date

Expiry Date

Tags

Class Metadata (fields defined per Class — see Section 11)

Source

OCR Text

AI Summary

Related Documents

Version History

Created By

Modified By

```

---

# 10. Assets

Assets represent real-world objects.

Examples

```
Frankfurt Apartment

BMW iX3

German Passport

Household Insurance

Starlink Mini

Mortgage

Investment Account
```

Every document links to an asset. An asset may declare a default Party (Section 8); documents filed under it inherit that Party unless overridden.

---

# 11. Document Classes & Metadata Schemas

Each Class in the taxonomy (Section 7) carries its own metadata schema — a fixed set of fields relevant to that kind of document — rather than every document sharing one universal field set. AI extracts only the fields defined for the leaf it classifies a document into.

Examples

```
Invoice            vendor, amount, currency, invoice_number, due_date, paid_status

Insurance Policy   insurer, policy_number, coverage_amount, premium, renewal_date

Contract           counterparty, effective_date, term_end_date, contract_value

Statement          account, period_start, period_end, closing_balance

Vehicle Registration   plate_number, VIN, registration_expiry
```

A Subclass inherits its Class's fields and may add more.

```
Statement

    Credit Card Statement   + statement_period, minimum_payment_due
```

---

# 12. Search

Search supports

## Keyword

```
passport
```

---

## OCR

```
BMW Service Munich
```

Depends on OCR Text extraction (Section 9) — deferred until structured metadata search (below) is proven out.

---

## AI Semantic

```
documents related to buying my apartment
```

---

## Filters

Domain / Subdomain / Class / Subclass

Asset

Context (Personal / Family / Business)

Person

Date

Workflow

Tags

Class Metadata (e.g. amount, vendor, policy number)

File Type

---

## Implementation Staging

Search is layered rather than built as one full-text/semantic system up front:

```
1. Canonical query fields

   Each Class's metadata schema (Section 11) maps its fields onto a
   small shared set of fields stored on every document that has them:

   search_amount    search_date    search_party    search_counterparty

   Lets a query like "everything over 500 due this month" work across
   Invoice, Statement, Contract, etc. without per-class query logic.

2. Structured filter backend

   Server-side filtering on Taxonomy Path, Party (Section 8), Tags,
   and the canonical fields above — replaces substring scanning with
   real queries.

3. AI query-rewrite

   The search bar stays natural language. A query such as "documents
   related to buying my apartment" is rewritten into a structured
   filter (Domain = Property, Asset = Frankfurt Apartment) instead of
   requiring a vector/embedding search — this fulfils AI Semantic
   search above without standing up separate search infrastructure.
```

OCR full-text (body) search is a later, separate phase — not required for stages 1–3.

---

# 13. Document Viewer

Three-panel layout.

Left

Document list

Center

PDF preview

Right

Metadata

AI Summary

Related Documents

Tags

Activity

Actions

---

Actions

Edit

Rename

Move

Share

Download

Delete

Version History

AI Chat

---

# 14. AI Features

## OCR

Automatic OCR after upload.

---

## Auto Classification

Classify each document against the taxonomy (Section 7) down to its most specific matching leaf (Class or Subclass).

When no existing leaf fits well, propose a new leaf with a reason and confidence score into a review queue, rather than forcing a mismatch or silently inventing a category.

Match documents to an existing Party (Section 8), reusing the same hint-and-match pattern already used for Assets, instead of creating duplicate people or entities.

---

## Taxonomy Review Queue

New-leaf proposals are tracked separately from individual document workflow (Section 15) — this governs the shared taxonomy, not a document's lifecycle.

```
On proposal

    Document files immediately under the nearest existing ancestor
    leaf — never left unclassified

    taxonomy_status: pending_review, proposed path stored alongside

    Checked against other pending proposals under the same parent for
    near-duplicates before creating a new one
```

```
Notification

    Proposal is recorded on the first matching document, but only
    surfaces in the review queue once 2 or more documents would land
    under it — avoids nagging over one-off documents
```

```
Review actions

    Approve as-is          adds the leaf to the taxonomy; attached
                            documents reclassified into it; future
                            classification includes it

    Approve with edit      rename / reparent before adding

    Merge into existing    AI proposal wasn't needed; attached
                            documents reclassified into the matched
                            existing leaf instead

    Reject                 proposal discarded; documents remain at
                            their ancestor-level classification
```

Approval is forward-only: it affects documents classified from that point on. Documents already filed elsewhere under the same parent are not automatically rescanned.

---

## Metadata Extraction

Extract the fields defined by the document's Class (Section 11) — e.g. vendor / amount / invoice_number for an Invoice, policy_number / premium / renewal_date for an Insurance Policy — rather than one universal field set.

Also extract, where applicable:

Dates

Companies

Addresses

Names

Property Address

Expiry Dates

---

## AI Summary

Example

> Household insurance policy covering Frankfurt apartment. Annual renewal on 1 August 2027. Includes water damage and liability.

---

## Suggested Tags

Automatically generate tags.

---

## Related Documents

Automatically detect

Contract

↓

Invoice

↓

Warranty

↓

Repair

---

## AI Chat

User can ask

"How much have I spent servicing my BMW?"

"What insurance policies expire next year?"

"Show me all mortgage documents."

"Summarize my apartment purchase."

---

# 15. Workflow

Documents move independently of cabinet.

```
Inbox

↓

Needs Action

↓

Waiting

↓

Completed
```

Example

```
Utility Bill

↓

Needs Action

↓

Paid

↓

Completed
```

---

# 16. Notifications

Examples

Insurance renewal

Passport expiry

Visa expiry

Mortgage payment

Tax deadline

Vehicle inspection

Warranty expiration

Medical appointment

---

# 17. Timeline View

Every document appears on a timeline.

```
July 2026

Apartment Contract

BMW Service

Passport Renewal

Tax Filing

Insurance Renewal
```

---

# 18. Mobile Features

Scan document

Upload photo

Camera OCR

Offline viewing

Biometric unlock

Quick search

Voice search

Widgets

---

# 19. Sharing

Generate secure share links.

Share with

Spouse

Family

Lawyer

Accountant

Insurance company

Landlord

---

Permission levels

View

Comment

Upload

Edit

Admin

---

# 20. Security

Mandatory encryption

AES-256 at rest

TLS in transit

Biometric login

Passcode

Two-factor authentication

Automatic backups

Audit log

Device management

Remote logout

---

# 21. Integrations

Cloud storage

Google Drive

Dropbox

OneDrive

iCloud

---

Calendar

Google Calendar

Apple Calendar

Outlook

---

Email

Gmail

Outlook

Apple Mail

---

Scanner

Apple Files

Adobe Scan

Microsoft Lens

Built-in camera

---

# 22. Analytics

Dashboard displays

Number of documents

Documents by category

Storage usage

Expiring documents

Recent uploads

Pending actions

Search frequency

---

# 23. Non-Functional Requirements

Fast search (<300 ms for indexed metadata)

Support at least 1 million documents

Offline support

Cross-platform

Responsive UI

Dark mode

Accessibility (WCAG 2.2 AA)

Automatic backups

Multi-device synchronization

High availability (99.9% uptime for cloud services)

---

# 24. Future Enhancements

- AI-generated life timeline
- Household inventory with photos and purchase values
- Financial net-worth dashboard
- Automatic email ingestion and document filing
- Family shared cabinet with role-based permissions
- Receipt scanning with expense categorization
- Voice assistant ("Find my passport")
- AI-powered tax preparation workspace
- Estate planning and emergency vault
- Smart reminders based on document content
- Personal knowledge graph linking people, assets, organizations, and events
- Digital will and legacy access for trusted contacts

---

# 25. Success Metrics

- Time to find a document: **< 10 seconds**
- Automatic classification accuracy: **> 95%**
- OCR extraction accuracy: **> 98%** for high-quality scans
- Metadata extraction accuracy: **> 90%**
- User manually edits fewer than **20%** of AI-suggested classifications
- 90% of uploads are searchable within **30 seconds**
- Average user satisfaction (CSAT): **≥ 4.5/5**
- Zero document duplication in the logical data model
- 100% encryption coverage for stored documents and metadata

---

# 26. Product Vision Statement

Life Cabinet should become the single trusted place where a user can instantly find, understand, and manage every important document in their life. Rather than acting as another cloud drive, it should function as an intelligent digital life assistant—organizing information around people, assets, events, and responsibilities, proactively surfacing what matters, and making document management effortless through AI.
