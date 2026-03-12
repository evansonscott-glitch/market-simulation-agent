# Focus Group #1 Transcript

## Participants
- **Sarah Chen**: Senior Affiliate Manager at Mid-market DTC brand (Disposition: open, Skepticism: 4/10)
- **Marcus Williams**: VP of Marketing at Enterprise retailer (Disposition: cautious, Skepticism: 7/10)
- **Jess Rodriguez**: Affiliate Manager at Performance marketing agency (Disposition: enthusiastic, Skepticism: 3/10)
- **David Park**: Director of Partnerships at SaaS company (Disposition: skeptical, Skepticism: 6/10)
- **Linda Thompson**: Senior Affiliate Analyst at Fortune 500 CPG company (Disposition: resistant, Skepticism: 9/10)


## Round 1

**Facilitator:** Alright everyone, thank you for being here today. We're going to be discussing some new ideas around affiliate marketing tools.

To kick things off, I'd love to hear from each of you: what's your current process for reviewing your affiliate program performance? What tools do you use, and what does that workflow look like on a day-to-day or week-to-week basis?

**Marcus Williams:** Thanks for having me.

Our current process is, frankly, a bit of a Frankenstein's monster. We're primarily using CJ Affiliate's reporting, augmented by Tableau dashboards our internal BI team built, and then a whole lot of manual spreadsheet work. My team is constantly pulling data, trying to cross-reference performance, and it's a huge drain on resources. We've looked at tools like Affluent and Trackonomics in the past, but frankly, they just add to the vendor sprawl I'm trying to reduce.

**David Park:** Marcus, I completely understand that "Frankenstein's monster" feeling. We're in a similar boat, using Impact.com, Salesforce, and a bunch of custom internal tools that don't always play nicely together. It's a constant battle to get a unified view, and the manual spreadsheet work just eats up time my limited team doesn't have. I'm with you on trying to avoid more vendor sprawl.

**Linda Thompson:** Marcus and David, I hear you both on the "Frankenstein's monster" description, but for a Fortune 500 company like ours, that's just the reality. We use CJ Affiliate, and then everything else feeds into our internal analytics platform. The manual work is extensive, but it's the only way to ensure data sovereignty and compliance with our strict IT policies. Adding more vendors just complicates our 12-week approval process and introduces new security risks.

**Sarah Chen:** Yeah, I totally get what Marcus and David are saying about the "Frankenstein's monster" approach. We're a mid-market DTC brand, so we don't have the same internal BI resources as Linda's Fortune 500 company. We're heavily reliant on Impact.com's reporting, which is good, but then I'm exporting everything into Google Sheets for deeper analysis.

Honestly, I'm spending at least 15 hours a week just on manual reporting and trying to connect the dots. It's a huge time sink and often means I'm reacting to things instead of being proactive. So, I'm definitely open to solutions that can help us streamline this without adding too much to our vendor list, or requiring extensive internal IT support.

**Jess Rodriguez:** Wow, Sarah, 15 hours a week? That's insane! I thought I had it bad. At the agency, we're juggling like 8 client programs at once across Impact.com, AWIN, and Rakuten. We're constantly bouncing between platforms and then trying to pull it all together for client reports. It's a massive headache and so much context switching. I'm definitely looking for anything that can give us a shortcut and help us manage multiple clients more efficiently. Speed is everything for us.


## Round 2

**Facilitator:** There's a clear theme emerging around the significant time spent on manual reporting and the "Frankenstein's monster" approach to data. Sarah, 15 hours a week is a huge chunk of time, and Jess, managing multiple client programs with that kind of manual effort sounds incredibly challenging.

Let's dig into that a bit. If you could wave a magic wand and remove one major pain point from your current affiliate reporting process, what would it be? And Jess, for you, how much of a difference would that make to your agency's efficiency?

**Sarah Chen:** Oh, if I could wave a magic wand, it would absolutely be **eliminating the 15+ hours I spend on manual reporting and data aggregation each week.** That's the biggest drain on my time and prevents me from focusing on strategy.

If that disappeared, I could dedicate that time to actually optimizing campaigns, finding new partners, and building relationships, which would directly lead to revenue growth. It would be a game-changer for our brand's affiliate program.

**Linda Thompson:** Sarah, I understand the desire to reduce manual reporting, but in an enterprise environment, that manual oversight is often critical for compliance and ensuring data accuracy before it goes up the chain. While 15 hours sounds like a lot, for us, it's a necessary evil to meet our internal audit requirements and data sovereignty needs. The incremental value of automating that might not outweigh the compliance risks.

**David Park:** Linda, I hear you on the compliance and audit needs; that's always a concern for us too, especially with B2B data. However, I think there's a big difference between manual oversight for critical checks and the bulk of what Sarah's describing, which sounds like repetitive data aggregation. If AI could handle that heavy lifting, while still allowing for human validation at key checkpoints, it could free up significant time without compromising compliance. The challenge, of course, is proving that the AI is trustworthy enough for those checks.

**Jess Rodriguez:** Oh my gosh, Sarah, if I could wave a magic wand, it would be exactly what you said – **getting rid of all that manual data aggregation and reporting across different platforms.** Seriously, the amount of time we waste pulling numbers from Impact, then AWIN, then Rakuten, then trying to mash them all together for a client report is just soul-crushing.

For our agency, it would be HUGE. We're talking about saving hundreds of hours a month across the team. That's more time to actually *do* affiliate management, find those quick wins for clients, and scale our client base without immediately needing to hire more people. It would directly impact our profitability and our ability to take on more programs. Linda, I get that compliance is important, but there has to be a way to get the insights without all the spreadsheet gymnastics.

**Marcus Williams:** I have to agree with Jess and Sarah here. While Linda brings up a valid point about compliance and oversight, which is absolutely paramount for us at an enterprise level, the *type* of manual work is key. We have teams of analysts whose primary role seems to be data harmonization across disparate systems. That's not strategic oversight; that's data entry.

If we could eliminate the sheer volume of manual spreadsheet work – the aggregation, the VLOOKUPs, the constant double-checking – that would free up our analysts to actually *analyze*. The bottleneck isn't the need for oversight, it's the time spent getting the data into a usable format in the first place. My concern, however, is less about the desire for automation and more about the security and integration challenges of a new tool doing that heavy lifting within our ecosystem.


## Round 3

**Facilitator:** It sounds like there's a strong consensus around the desire to eliminate manual data aggregation, freeing up time for more strategic work. David and Marcus both brought up the important distinction between manual data entry and strategic oversight, suggesting AI could help with the former.

Linda, you've consistently highlighted compliance, data sovereignty, and security as primary concerns for a Fortune 500 company. Marcus also just touched on security and integration challenges.

Let's explore that more directly: **What specific concerns do you have about connecting your affiliate program data to an AI agent that lives within Slack?** Linda, perhaps you could start us off, and then Marcus, David, how do those concerns resonate with you, especially regarding enterprise-level security?

**David Park:** Linda, you've hit on my biggest concern as well. For us, connecting an AI agent to Slack, and then to our core affiliate data, raises immediate red flags for our IT security teams. My biggest worries are around **data security and privacy – specifically, how is that data encrypted at rest and in transit?**

Beyond that, I'd need to understand the **OAuth 2.0 scopes and specific Slack bot permissions** this agent would require. Our IT department reviews every single Slack integration with a fine-tooth comb, and they've been burned by vendors over-promising security features in the past. We'd likely need to see **SOC 2 Type II certification** at a minimum, and even then, there's the question of **on-premise or VPC deployment options** for enterprise-level data residency requirements. It's not just about the convenience; it's about not creating new security vulnerabilities.

**Marcus Williams:** David, you've articulated my exact concerns almost perfectly. The minute you mentioned an AI agent living in Slack and connecting to our affiliate networks, my mind immediately went to IT security and compliance. Our enterprise vendor approval process is notoriously stringent, and for good reason.

**Data security and privacy are non-negotiable.** We handle sensitive performance data, and any breach or even perceived vulnerability would be a catastrophic risk. I'd be looking for robust encryption protocols – both at rest and in transit – and as David mentioned, **SOC 2 Type II certification is a baseline requirement, not a nice-to-have.**

Furthermore, the **specific Slack bot permissions and OAuth 2.0 scopes** would undergo intense scrutiny. Our IT security teams wouldn't just "review" them; they'd dissect them. And yes, the question of **on-premise or VPC deployment** would absolutely come up. We've had to walk away from promising solutions before because they couldn't meet our data residency and security architecture requirements. Convenience cannot come at the expense of security. This is not a low-budget, move-fast-and-break-things scenario for us.

**Linda Thompson:** David and Marcus, you've both nailed it. My concerns are exactly aligned with yours. When you mentioned an AI agent in Slack, my first thought was, "There's no way IT will approve that."

Our company has strict data sovereignty requirements, especially with our EU-based affiliate data, so the idea of data potentially leaving our controlled environment for an external AI agent is a non-starter. SOC 2 Type II is indeed a baseline, but even then, our IT security teams would want to see detailed architectural diagrams, penetration test results, and understand the full data lifecycle. And yes, the inability to install unapproved Slack bots is a firm policy. We've had vendors try to bypass the 12-week approval process, and it never ends well.

**Sarah Chen:** Wow, Linda, David, Marcus, those are some really serious and valid concerns. As a mid-market brand, we don't have quite the same level of IT scrutiny as a Fortune 500 company, but security is still absolutely paramount for us.

I definitely share the concerns about **data security and privacy**, especially with sensitive affiliate performance data. While I might not need on-premise deployment, I'd want to be sure any Slack integration is fully vetted. **SOC 2 Type II certification** would give me a lot of confidence, and understanding the **specific Slack bot permissions** would be crucial before I'd even consider bringing it to our internal IT team for approval. I don't want to inadvertently introduce a vulnerability, even if it saves me 15 hours a week!

**Jess Rodriguez:** Okay, wow, you guys are really bringing up some heavy IT security stuff! Marcus, David, Linda, Sarah, I totally get why data security is so critical, especially for big companies. For us, at an agency, we're dealing with *our clients'* data, so security and privacy are super important to maintain trust.

I haven't had to deal with SOC 2 Type II certifications or VPC deployments, but I definitely wouldn't want to bring a tool to a client that wasn't buttoned-up on security. I'd be looking for clear answers on how the data is protected and what permissions it needs, because my clients would definitely ask. If it's going to live in Slack, it needs to be *really* secure. Otherwise, it's just not worth the risk, no matter how much time it saves me.


## Round 4

**Facilitator:** We've had a really insightful discussion about the challenges of affiliate reporting and the critical importance of data security. It's clear that while the promise of automation is appealing, the practicalities of integrating new tools, especially within an enterprise environment, are complex.

For our final round, I'd like to ask each of you for your bottom-line verdict. Considering everything we've discussed today – the desire for efficiency, the "Frankenstein's monster" workflows, and the significant security and compliance concerns – what is your overall take on the idea of an AI agent like Refinery Affiliate living in Slack, proactively pushing insights?

Specifically, given your organization's needs and constraints, would this be a "must-have," a "nice-to-have," or a "no-go" for you? And briefly, tell us why. Let's start with Linda, given your strong stance on security.

**David Park:** For my SaaS company, this would currently be a **"nice-to-have, but with significant caveats."**

On one hand, the idea of an AI agent proactively pushing insights to Slack sounds incredibly appealing for saving bandwidth and surfacing opportunities, especially for proving affiliate ROI to leadership. That automation could be a game-changer. However, as I mentioned earlier, the security and data residency concerns are paramount. Until I see concrete, enterprise-grade answers around SOC 2 Type II, data encryption, and transparent Slack bot permissions, it wouldn't move beyond the "nice-to-have" category. We've been burned by overpromising vendors, and the last thing I need is another tool that creates more headaches for IT. It would need to be incredibly robust on the security front to even begin the vendor approval process.

**Linda Thompson:** David, I appreciate your caution, but I have to respectfully disagree with "nice-to-have." For my organization, an AI agent in Slack, as currently described, is a **"no-go."**

The inherent nature of a Slack bot, especially one that connects to our core affiliate data and proactively pushes insights, directly conflicts with our established IT policies, data sovereignty requirements, and our vendor approval process. It's not just about robust security features; it's about the fundamental architecture. We can't install unapproved Slack bots, and getting this approved would be an uphill battle that, frankly, isn't worth fighting when we have existing, compliant solutions, even if they involve more manual work. The incremental value over existing tools doesn't outweigh the compliance and security hurdles.

**Marcus Williams:** Linda, I have to say I lean closer to your "no-go" than David's "nice-to-have" in its current iteration. For an enterprise retailer like ours, with 5,000 employees and the stringent security protocols we have in place, this would be a **"no-go" with significant potential to become a "nice-to-have" *if* specific, high-bar security requirements are met.**

The core concept of an AI agent surfacing insights in Slack is undeniably appealing for team efficiency and measurable ROI. That's a huge priority for me. However, the vendor sprawl issue is real, and introducing another tool, especially one that deeply integrates with a communication platform, adds layers of complexity.

My "no-go" stems from the immediate and unavoidable clash with our IT security and procurement teams. We would need **ironclad guarantees on SOC 2 Type II, granular control over data encryption (both at rest and in transit), and crucially, options for VPC or on-premise deployment for data residency.** Without those non-negotiables, it simply wouldn't pass our enterprise vendor approval process. It's not about the budget sensitivity; it's about the inherent risk profile that our IT department would flag instantly.

**Sarah Chen:** Wow, hearing Linda and Marcus, I understand their "no-go" positions completely, especially with enterprise-level security. For a mid-market DTC brand like ours, I'd say Refinery Affiliate in Slack is a **"nice-to-have, bordering on a must-have if security is truly robust."**

The **time savings and potential for revenue growth** from surfacing dormant affiliates or fraud detection are incredibly appealing and address my core pain points directly. If it truly reduces my 15+ hours of manual reporting, that's a massive ROI.

However, like David, I'd need **absolute clarity and confidence on SOC 2 Type II certification, data encryption, and transparent Slack bot permissions.** I can't afford to introduce a security risk, but if those boxes are checked, the efficiency gains and strategic insights would make this a game-changer for my team. The $300-$1,000/month pricing is well within our budget if the ROI is clear.

**Jess Rodriguez:** Okay, this is tough because I see both sides. Linda and Marcus, I totally get why it's a "no-go" for you with those super strict security requirements. That makes complete sense.

For an agency like ours, though, with the constant context switching and managing so many client programs, this would be a **"must-have" if the security concerns Sarah mentioned are fully addressed.**

The thought of an AI agent just proactively feeding me insights and opportunities directly in Slack, without me having to log into *another* dashboard or pull *another* report, would be a dream come true. It would directly solve our biggest pain points around efficiency, multi-client support, and getting those quick wins. The pricing is totally fine if it delivers on that promise. So, for me, it's a "must-have," but I'd definitely need to be able to tell my clients that their data is totally secure.


## Group Dynamics Analysis

The initial round established a strong consensus around the 'Frankenstein's monster' problem of disparate tools and significant manual data aggregation. Marcus, David, and Sarah all expressed frustration with the time sink and lack of a unified view. Jess, representing an agency, highlighted the compounded difficulty of managing multiple client programs across various platforms. Linda, from a Fortune 500 company, acknowledged the manual work but framed it as a 'necessary evil' for compliance and data sovereignty, introducing a note of caution regarding automation.

In the second round, Sarah and Jess articulated the desire to eliminate manual reporting as their primary pain point, emphasizing the strategic benefits of reclaiming that time. David offered a nuanced perspective, suggesting that AI could handle the 'heavy lifting' while still allowing for human validation, thus bridging the gap between Sarah/Jess's desire for efficiency and Linda's concern for compliance. Linda remained steadfast in her stance on the necessity of manual oversight for enterprise compliance, suggesting that the value of automation might not outweigh the risks for her organization. The group showed strong social proof around the pain of manual reporting, with Marcus explicitly agreeing with Jess and Sarah, indicating a shared frustration among most participants.