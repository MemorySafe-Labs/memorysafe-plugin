# MemorySafe Beta Privacy Policy

**Effective date:** August 3, 2026  
**Version:** 0.1 - Private Beta

This Privacy Policy explains how MemorySafe Labs Inc. ("MemorySafe Labs," "we," "us," or "our") handles personal information in connection with the MemorySafe private beta software, connector, dashboard, and support activities (the "Beta").

This Policy applies to information handled by MemorySafe Labs and the MemorySafe Beta. It does not replace the privacy terms that apply to ChatGPT, OpenAI, your operating system, your device-backup provider, or other services you choose to use.

## 1. Who we are

MemorySafe Labs Inc. is a corporation incorporated under the Canada Business Corporations Act, federal corporation number 18085285, and registered in Quebec under enterprise number (NEQ) 1182359472.

**Person responsible for the protection of personal information:** Carla Paetzold Centeno  
**Privacy contact:** contact@memorysafe.ca

## 2. Privacy summary for the private beta

- Memory content is stored primarily in a local SQLite database on the computer running the connector.
- MemorySafe Labs does not operate a central memory-content database for this private beta.
- The Beta does not independently copy complete ChatGPT conversation history or read ChatGPT's built-in memory.
- ChatGPT sends app requests to the local connector and receives app responses through an authorized OpenAI tunnel connection. Content included in those requests and responses is processed by OpenAI under the terms that apply to the user's ChatGPT account or workspace.
- Automatic Mode is optional and off by default for a new installation.
- Automatic Mode is designed to save only short, directly stated, durable, non-sensitive facts from chats where MemorySafe is selected.
- The Beta does not currently add application-level encryption to its local database.

## 3. Information the Beta may handle

### 3.1 Memory content

The Beta may process and store content that you explicitly ask ChatGPT to remember or that ChatGPT submits as an eligible candidate while Automatic Mode is enabled. Examples include preferences, project details, decisions, recurring tasks, and other durable facts.

### 3.2 Memory metadata

For each memory, the local database may store:

- a MemorySafe identifier;
- category;
- importance and confidence scores;
- whether the memory is protected from normal cleanup;
- whether it was submitted manually or through Automatic Mode;
- active or deleted state; and
- creation, update, and deletion timestamps.

### 3.3 Settings and operational records

The local database may store whether Automatic Mode is enabled and decision records such as store, protect, merge, skip, and forget events. These records may include identifiers, reasons, timestamps, and content-size measurements. The current Beta's decision records do not intentionally create a separate full copy of every chat message.

### 3.4 ChatGPT app requests and responses

When MemorySafe is selected in a chat, ChatGPT may send the local connector an app request containing a memory candidate, search query, memory identifier, or settings instruction. The connector returns an app response, which may include memory content, metadata, health statistics, or confirmation of an action. These transmissions pass through OpenAI's systems.

### 3.5 Support and beta feedback

If you contact us, we may receive your name, email address, message, diagnostic details you choose to provide, and related correspondence. Do not send passwords, access keys, payment-card data, protected health information, or copies of private memories in support messages unless we specifically request necessary information through a secure method.

### 3.6 Information we do not intentionally collect centrally

The current private beta contains no MemorySafe Labs analytics or telemetry service that centrally receives your complete local memory database. We do not sell memory content or personal information.

## 4. Why we handle information

We handle information as necessary to:

- provide memory storage, recall, forgetting, settings, and dashboard functions;
- identify and merge duplicate or near-duplicate memories;
- apply Automatic Mode safety and quality filters;
- maintain security, diagnose problems, and prevent misuse;
- respond to support requests and beta feedback;
- improve the Beta using feedback and non-sensitive technical findings; and
- comply with applicable law.

We do not use private-beta memory content for advertising or to build marketing profiles.

## 5. Automatic Mode and consent

Automatic Mode is optional and off by default for a new installation. We request a separate affirmative action before it is enabled. Accepting the Terms of Use alone does not enable Automatic Mode.

When enabled, Automatic Mode may store up to a small number of concise memory candidates from a user turn in a chat where MemorySafe is selected. It is designed not to store complete messages, assistant-generated text, inferred information, temporary remarks, or personal information about third parties.

Automatic Mode filters attempt to reject likely passwords and secrets, payment and government identifiers, contact details, precise addresses, and medical or health information. The filters are experimental and are not guaranteed to detect every sensitive item.

You may withdraw Automatic Mode consent at any time by turning the mode off. This stops future automatic captures but does not erase information already stored.

## 6. Sensitive information and prohibited content

The Beta is not designed to store protected health information, payment-card data, passwords, authentication codes, private keys, API keys, or highly sensitive identity information. Do not ask the Beta to store these categories manually. Do not submit another person's personal information unless you have a lawful basis and authority to do so.

If the Beta detects potentially sensitive content during Automatic Mode, it is designed to skip the capture and record a general skip reason. Detection may fail, so you should review memories and avoid entering sensitive information in the first place.

## 7. How information is shared

### 7.1 OpenAI and ChatGPT

Information included in a MemorySafe app request or response is transmitted through and processed by OpenAI. OpenAI handles that information under the terms, privacy policy, data controls, and workspace settings that apply to your ChatGPT account. OpenAI and MemorySafe Labs act under their respective agreements and responsibilities; MemorySafe Labs does not control OpenAI's independent processing.

OpenAI privacy information is available at https://openai.com/privacy/ and information about apps in ChatGPT is available at https://help.openai.com/en/articles/11487775-apps-in-chatgpt.

### 7.2 Service providers

The current private beta does not use a MemorySafe Labs cloud provider to store local memory content. We may use ordinary business service providers, such as email hosting, to process support communications. They may process information only for the service they provide and subject to applicable contractual and legal protections.

### 7.3 Legal and safety reasons

We may disclose information if reasonably necessary to comply with law, legal process, or a valid government request; protect the rights, safety, and security of users, MemorySafe Labs, or others; investigate abuse; or establish, exercise, or defend legal claims.

### 7.4 Business changes

If MemorySafe Labs is involved in a financing, reorganization, merger, acquisition, or sale, information may be disclosed under appropriate confidentiality and legal protections. We will provide notice when required by law before personal information becomes subject to materially different practices.

We do not sell personal information.

## 8. Storage location and international processing

The primary MemorySafe database is stored on the computer running the connector at the installation's configured local data path. MemorySafe Labs does not choose the physical location of that computer or the user's device backups.

Your operating system, backup software, cloud-drive configuration, or device-management tools may copy the local database. Those copies are controlled by the relevant user, organization, or third-party provider.

App requests and responses are processed through OpenAI's systems and may be processed outside Quebec or Canada according to the user's OpenAI account, workspace, and applicable OpenAI terms. Support email may also be processed outside Quebec or Canada by the email provider. Privacy laws in another jurisdiction may differ from those in your location.

## 9. Retention, forgetting, and deletion

### 9.1 Active memories

Local memory content and metadata remain in the local database until the user takes a deletion action, removes the database, or loses or replaces the device. MemorySafe Labs does not centrally control the user's local retention period.

### 9.2 Current Forget behavior

In Beta version 0.2.0, the Forget action removes a selected memory from active recall and marks it as deleted. The underlying memory record, including its content, remains in the local SQLite database. It is not returned by normal memory searches.

To completely erase the current local memory store, the user must securely delete the local `data/memorysafe.sqlite3` database and its related SQLite sidecar files, if present, after stopping the connector. This deletes all MemorySafe memories and operational records on that installation. Users who need assistance may contact contact@memorysafe.ca.

Deleting a local MemorySafe record does not delete copies retained in ChatGPT conversation history, OpenAI systems, device backups, support correspondence, or other third-party services. Those copies are governed by the applicable service and user settings.

### 9.3 Support records

We retain support and beta-feedback correspondence only as long as reasonably necessary for support, security, legal, and product-improvement purposes. Our target is deletion or anonymization within 24 months after the matter is closed, unless a longer period is required by law or reasonably necessary for a legal claim or security investigation.

## 10. Security

We use measures intended to protect the Beta, including local storage, an authorized tunnel connection, access credentials, limited tool actions, and Automatic Mode filters. However, no system is completely secure.

The current Beta does not add application-level encryption to the local SQLite database. Users should enable device encryption, use a strong device password, protect their ChatGPT and operating-system accounts, restrict access to the computer, maintain appropriate backups, and never paste tunnel keys or API credentials into a chat.

If you believe MemorySafe information has been accessed or disclosed without authorization, contact us promptly at contact@memorysafe.ca.

## 11. Your choices and rights

Depending on applicable law, you may have rights to access, correct, delete, or obtain information about the use and disclosure of your personal information, and to withdraw consent where processing is based on consent.

The Beta provides local tools to view and search active memories, remove a memory from active recall, and disable Automatic Mode. For complete local deletion, follow Section 9.2. You may also contact contact@memorysafe.ca to request assistance or exercise a privacy right concerning information held by MemorySafe Labs, such as support correspondence.

We may need to verify identity before responding to a request. We will respond within the period required by applicable law. If we cannot fulfill a request, we will explain why, subject to legal restrictions.

You may submit a privacy complaint to us at contact@memorysafe.ca. You may also have the right to contact the Commission d’accès à l’information du Québec or another competent privacy regulator.

## 12. Children

The private Beta is intended only for adults aged 18 or older. We do not knowingly invite or authorize children to use it. If you believe a child has provided personal information through the Beta, contact us so we can take appropriate action.

## 13. Changes to this Policy

We may update this Policy as the Beta changes. We will identify the new effective date and provide reasonable notice of material changes through the Beta, by email, or by another appropriate method. If a change requires new consent, we will request it before the new processing begins.

## 14. Contact

**Privacy Officer**  
Carla Paetzold Centeno  
MemorySafe Labs Inc.  
Federal corporation number: 18085285  
Quebec enterprise number (NEQ): 1182359472  
Email: contact@memorysafe.ca
