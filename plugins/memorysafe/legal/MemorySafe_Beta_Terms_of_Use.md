# MemorySafe Beta Terms of Use

**Effective date:** September 20, 2026  
**Version:** 0.2 - Private Beta

These Terms of Use ("Terms") are a legal agreement between you and MemorySafe Labs Inc. ("MemorySafe Labs," "we," "us," or "our") governing your access to and use of the MemorySafe private beta software, connector, dashboard, and related services (collectively, the "Beta").

By installing, connecting, accessing, or using the Beta, or by selecting an acceptance control presented with these Terms, you agree to these Terms. If you do not agree, do not use the Beta.

## 1. About MemorySafe Labs

MemorySafe Labs Inc. is a corporation incorporated under the Canada Business Corporations Act, federal corporation number 18085285, and registered in Quebec under enterprise number (NEQ) 1182359472.

Contact: contact@memorysafe.ca

## 2. Eligibility and beta participation

You must be at least 18 years old and legally able to enter into this agreement. The Beta is invitation-only unless we state otherwise. You may use it only for your own lawful evaluation and in accordance with any testing instructions we provide.

The Beta is experimental and may be incomplete, unavailable, inaccurate, or changed without notice. Features may fail, memories may not be captured or retrieved as expected, and stored information may be lost. Do not rely on the Beta as the only copy of important information.

## 3. What the Beta does

MemorySafe provides local memory-governance tools for compatible AI assistants. Depending on the version and settings available to you, the Beta may allow you to:

- save concise facts, preferences, decisions, project details, and tasks;
- search and retrieve stored memories;
- remove a selected memory from active recall;
- review memory-health information and recent memories in a dashboard;
- enable or disable optional Automatic Mode; and
- merge duplicate or near-duplicate memories.

MemorySafe runs on your own computer and connects to compatible AI assistants through the Model Context Protocol. In this beta those are Claude Code, Claude Desktop, and Codex, and, on macOS only, ChatGPT through OpenAI's Secure MCP Tunnel. One local SQLite database serves all of them, so a memory saved in one assistant is available in the others on that computer.

The Beta does not independently copy your conversation history and does not read an assistant's own built-in memory. For an assistant that runs on your computer, MemorySafe requests and responses travel between that assistant and the local connector on the same machine. ChatGPT is the exception: it reaches the connector through OpenAI's tunnel, so those requests and responses pass through OpenAI's systems.

## 4. Automatic Mode is optional

Automatic Mode is off by default for a new installation. It may be enabled only through a separate affirmative action. When enabled, it may save short, directly stated, durable, non-sensitive facts from chats in which MemorySafe is selected. It is designed not to save complete messages or conversations automatically.

Automatic Mode uses filters intended to reject likely secrets, payment and government identifiers, contact details, precise addresses, and medical or health information. These filters are experimental and may not identify every sensitive item. You remain responsible for what you enter in a chat and for reviewing saved memories.

You may disable Automatic Mode at any time. Disabling it stops new automatic captures but does not erase memories already stored.

## 5. Your content and instructions

You retain any rights you have in the content you provide. You give MemorySafe Labs a limited, non-exclusive permission to process that content only as necessary to operate, secure, support, and improve the Beta in accordance with the Privacy Policy and your instructions.

The current private beta is designed so that memory content is stored on your device rather than in a central MemorySafe Labs database.

Memory content still reaches the assistant you are using, because that is what asking it to save, find, display, or use a memory means. Whatever that assistant then includes in its own conversation is sent to and processed by its provider -- Anthropic for Claude Code and Claude Desktop, OpenAI for Codex and ChatGPT -- under your separate agreement with that provider, not under these Terms. For ChatGPT on macOS, the requests and responses themselves also pass through OpenAI's tunnel.

You are responsible for the accuracy, lawfulness, and appropriateness of your content. Do not use the Beta to store passwords, authentication codes, API keys, payment card data, protected health information, information about another person without proper authority, or content that you do not have the right to process.

## 6. Acceptable use

You must not:

- use the Beta illegally, fraudulently, deceptively, or to harm another person;
- probe, attack, bypass, or interfere with the security or operation of the Beta, its connector, or related systems;
- introduce malware or use the Beta to distribute malicious content;
- attempt to access another user's memories or computer without authorization;
- use the Beta to make high-impact decisions about another person in employment, housing, credit, insurance, health care, education, or legal services;
- use the Beta as a substitute for qualified medical, legal, financial, safety, or other professional advice; or
- violate the applicable terms, usage policies, or permissions of an assistant you connect MemorySafe to, or of its provider.

## 7. Third-party services

The Beta depends on the assistants you connect it to and their providers, such as Anthropic or OpenAI, on your operating system, and, for ChatGPT on macOS, on an authorized tunnel service. Its first start also downloads uv, a Python build, and pinned packages from their distributors. These are third-party services governed by their own terms and privacy practices. MemorySafe Labs does not control and is not responsible for the availability, security, accuracy, or conduct of third-party services.

## 8. Privacy

Our MemorySafe Beta Privacy Policy explains how information is handled. It forms part of these Terms. Automatic Mode consent is separate from acceptance of these Terms.

## 9. Security and your responsibilities

You are responsible for keeping your device, your accounts with the assistants you connect, API or runtime credentials, and local files secure. Do not share access keys in chats or support messages. The Beta does not currently add application-level encryption to the local MemorySafe database; protection depends in part on your device and operating-system security settings.

No system is completely secure. Notify us promptly at contact@memorysafe.ca if you believe the Beta or your MemorySafe data has been compromised.

## 10. Feedback

You may choose to provide feedback, bug reports, or suggestions. You grant us permission to use that feedback without restriction or compensation, provided that we do not publicly identify you without permission. Do not include memory content or sensitive personal information in a bug report unless it is necessary and you agree to provide it.

## 11. Changes, suspension, and termination

We may update, restrict, suspend, or discontinue the Beta at any time. We may suspend or terminate access if we reasonably believe you violated these Terms, created a security or legal risk, or used the Beta in a harmful manner.

You may stop using the Beta at any time and disconnect it from the assistants you connected. The `memorysafe uninstall` command lists what is on the computer and removes it; it keeps your memories unless you pass `--purge`, and neither removes information retained by third-party services. See the Privacy Policy for deletion instructions.

## 12. Disclaimers

TO THE MAXIMUM EXTENT PERMITTED BY LAW, THE BETA IS PROVIDED "AS IS" AND "AS AVAILABLE," WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, EXPRESS, IMPLIED, OR STATUTORY. MEMORYSAFE LABS DISCLAIMS IMPLIED WARRANTIES OR CONDITIONS OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, NON-INFRINGEMENT, ACCURACY, AVAILABILITY, SECURITY, AND THAT DATA WILL NOT BE LOST.

THE BETA DOES NOT PROVIDE MEDICAL, LEGAL, FINANCIAL, OR OTHER PROFESSIONAL ADVICE. AI-GENERATED OUTPUT AND MEMORY CLASSIFICATIONS MAY BE INCORRECT. YOU SHOULD REVIEW IMPORTANT INFORMATION AND USE INDEPENDENT JUDGMENT.

Some jurisdictions do not allow certain disclaimers, so some of the above may not apply to you.

## 13. Limitation of liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, MEMORYSAFE LABS AND ITS DIRECTORS, OFFICERS, EMPLOYEES, CONTRACTORS, AND AFFILIATES WILL NOT BE LIABLE FOR INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES, OR FOR LOSS OF DATA, PROFITS, REVENUE, GOODWILL, OR BUSINESS OPPORTUNITY, ARISING FROM OR RELATED TO THE BETA.

TO THE MAXIMUM EXTENT PERMITTED BY LAW, OUR TOTAL AGGREGATE LIABILITY ARISING FROM OR RELATED TO THE BETA WILL NOT EXCEED THE GREATER OF (A) CAD $100 OR (B) THE AMOUNT YOU PAID MEMORYSAFE LABS FOR THE BETA DURING THE 12 MONTHS BEFORE THE EVENT GIVING RISE TO THE CLAIM.

Nothing in these Terms limits liability that cannot legally be limited or excludes rights you may have under mandatory consumer-protection law.

## 14. Governing law and disputes

These Terms are governed by the laws of Quebec and the federal laws of Canada applicable there, without regard to conflict-of-law principles. Subject to any mandatory consumer rights, the courts of Quebec will have exclusive jurisdiction over disputes relating to these Terms or the Beta.

Before starting formal proceedings, you and MemorySafe Labs agree to attempt in good faith to resolve the dispute by written notice to contact@memorysafe.ca and a reasonable opportunity to respond.

## 15. Changes to these Terms

We may update these Terms as the Beta changes. We will identify the effective date and provide reasonable notice of material changes through the Beta, by email, or by another appropriate method. If you do not agree to updated Terms, you must stop using the Beta.

## 16. General terms

These Terms and the Privacy Policy are the entire agreement between you and MemorySafe Labs concerning the Beta. If a provision is unenforceable, it will be modified only to the extent necessary, and the remaining provisions will continue in effect. Our failure to enforce a provision is not a waiver. You may not transfer these Terms without our consent. We may transfer them as part of a reorganization, financing, merger, acquisition, or sale of the Beta, subject to applicable law.

## 17. Contact

MemorySafe Labs Inc.  
Federal corporation number: 18085285  
Quebec enterprise number (NEQ): 1182359472  
Email: contact@memorysafe.ca

