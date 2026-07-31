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

# 7. Cabinet Structure

Example

```
Property

    Frankfurt Apartment

        Contracts

        Utilities

        Repairs

        Photos

        Correspondence

        Receipts

    Munich Apartment

    Hyderabad Apartment
```

---

Vehicle

```
BMW iX3

Registration

Insurance

Service

Parking

Repairs

Invoices
```

---

Health

```
Subbu

Medical Records

Vaccinations

Dental

Insurance Claims

Prescriptions
```

---

# 8. Document Model

Each document contains:

```
UUID

Title

Original filename

Description

Category

Asset

Owner

Document Type

Workflow Status

Document Date

Upload Date

Expiry Date

Tags

Source

OCR Text

AI Summary

Related Documents

Version History

Created By

Modified By

```

---

# 9. Assets

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

Every document links to an asset.

---

# 10. Categories

Examples

```
Contract

Invoice

Receipt

Certificate

Warranty

Photo

Medical Report

Tax Document

Correspondence

Insurance Policy

License

Statement

Utility Bill

Loan Document

Maintenance Report
```

---

# 11. Search

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

---

## AI Semantic

```
documents related to buying my apartment
```

---

## Filters

Category

Asset

Person

Date

Workflow

Tags

Document Type

File Type

---

# 12. Document Viewer

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

# 13. AI Features

## OCR

Automatic OCR after upload.

---

## Auto Classification

Detect

- invoice
- passport
- insurance
- medical
- contract

---

## Metadata Extraction

Extract

Dates

Companies

Addresses

Names

Invoice Numbers

Policy Numbers

Vehicle Registration

Property Address

Amounts

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

# 14. Workflow

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

# 15. Notifications

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

# 16. Timeline View

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

# 17. Mobile Features

Scan document

Upload photo

Camera OCR

Offline viewing

Biometric unlock

Quick search

Voice search

Widgets

---

# 18. Sharing

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

# 19. Security

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

# 20. Integrations

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

# 21. Analytics

Dashboard displays

Number of documents

Documents by category

Storage usage

Expiring documents

Recent uploads

Pending actions

Search frequency

---

# 22. Non-Functional Requirements

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

# 23. Future Enhancements

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

# 24. Success Metrics

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

# 25. Product Vision Statement

Life Cabinet should become the single trusted place where a user can instantly find, understand, and manage every important document in their life. Rather than acting as another cloud drive, it should function as an intelligent digital life assistant—organizing information around people, assets, events, and responsibilities, proactively surfacing what matters, and making document management effortless through AI.