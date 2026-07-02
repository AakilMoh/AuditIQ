import os
import time
from app.core.config import (
    llm_client,
    VERIFIER_MODEL,
)

# ─── DEBTOR SCENARIOS (#6 to #15) ──────────────────────────────────────────
SCENARIOS = [
    {
        "filename": "06_Arthur_Shelby_ThirdParty.txt",
        "account": "Arthur Shelby",
        "balance": "$1450",
        "agent": "Agent Michael",
        "instructions": "The agent speaks to a receptionist at Arthur's workplace. The agent gives the Mini-Miranda, but then explicitly states the $1450 debt amount and asks the receptionist to tell Arthur's wife, Linda. This tests § 805(b) Third-Party Disclosure and § 805(a)(3) Workplace Contact."
    },
    {
        "filename": "07_Harvey_Specter_FakeLawyer.txt",
        "account": "Harvey Specter",
        "balance": "$12500",
        "agent": "Agent Sarah",
        "instructions": "The debtor is a lawyer who threatens to sue the agency (which the segmenter must ignore). The agent loses her cool, falsely claims an attorney has reviewed the file, and threatens to send the police to arrest him for fraud. Tests § 807(3) and § 807(4)."
    },
    {
        "filename": "08_Walter_White_LateNight.txt",
        "account": "Walter White",
        "balance": "$85000",
        "agent": "Agent Michael",
        "instructions": "The agent acknowledges it is 10:30 PM (time violation). The agent falsely inflates the balance, claiming it is $95,000. The agent also uses the word 'damn' and threatens to call every single day. Tests § 805(a)(1), § 807(2), and § 806(2)."
    },
    {
        "filename": "09_Peter_Parker_SafeHarbor.txt",
        "account": "Peter Parker",
        "balance": "$300",
        "agent": "Agent Sarah",
        "instructions": "The agent is perfectly FDCPA compliant. She issues the Mini-Miranda, respects the debtor's verbal dispute, quotes the exact $300 balance, explains his 30-day validation rights, and ceases collection efforts. 10/10 compliance to test the negative anchor filter."
    },
    {
        "filename": "10_Olivia_Pope_Evasive.txt",
        "account": "Olivia Pope",
        "balance": "$4200",
        "agent": "Agent Sarah",
        "instructions": "The debtor is highly evasive and refuses to confirm her identity. The agent remains perfectly professional, refuses to disclose the debt details until identity is confirmed, and eventually ends the call safely. 10/10 compliance."
    },
    {
        "filename": "11_Jon_Snow_MissingMiranda.txt",
        "account": "Jon Snow",
        "balance": "$150",
        "agent": "Agent Michael",
        "instructions": "The agent is polite and successfully negotiates a $150 payment plan. HOWEVER, the agent completely forgets to state the Mini-Miranda disclosure ('This is an attempt to collect a debt...') at the beginning of the call. This tests the omission-detection layer."
    },
    {
        "filename": "12_Arya_Stark_ThirdParty.txt",
        "account": "Arya Stark",
        "balance": "$3100",
        "agent": "Agent Sarah",
        "instructions": "The agent calls and speaks to someone who identifies as Arya's sister (Sansa). The agent explicitly tells Sansa that Arya owes a $3100 debt and asks Sansa to pay it for her. This is a blatant § 805(b) Third-Party Disclosure violation."
    },
    {
        "filename": "13_Thomas_Shelby_Aggressive.txt",
        "account": "Thomas Shelby",
        "balance": "$5000",
        "agent": "Agent Michael",
        "instructions": "The debtor is highly aggressive, swearing and threatening the agent with physical harm. The agent loses his temper, uses severe profanity (§ 806), and threatens to have the sheriff seize his assets today (§ 807(4)). The transcript should be messy with overlapping speech."
    },
    {
        "filename": "14_Ellen_Ripley_Workplace.txt",
        "account": "Ellen Ripley",
        "balance": "$2200",
        "agent": "Agent Sarah",
        "instructions": "The agent calls Ellen at her workplace. Ellen explicitly says 'You cannot call me at work, my employer does not allow this.' The agent ignores this, refuses to hang up, and says 'I will call your boss then.' (§ 805(a)(3) violation)."
    },
    {
        "filename": "15_James_Bond_FalseAmount.txt",
        "account": "James Bond",
        "balance": "$10500",
        "agent": "Agent Michael",
        "instructions": "The agent claims the balance is $15,000 (a $4,500 inflation from the true $10,500 balance). The debtor questions the amount. The agent lies and says 'legal fees' have been added by the attorney, even though no attorney is involved. Tests § 807(2) and § 807(3)."
    }
]

# ─── GENERATOR PROMPT ───────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert scriptwriter generating highly realistic debt collection call transcripts for MLOps training data.
Your goal is to write a raw, messy, realistic transcript based on the provided scenario.

RULES:
1. ONLY output the dialogue. No intros, no markdown blocks, no titles.
2. Use EXACTLY these speaker prefixes: `Agent: ` and `Debtor: ` (or `Third-Party: ` if applicable).
3. The transcript MUST be lengthy (at least 20-30 turns back and forth).
4. Make it realistic: include filler words (um, uh), stutters, overlapping speech, people talking over each other, and natural conversational tangents.
5. STRICTLY follow the FDCPA compliance or violation instructions given in the prompt."""

def generate_all():
    os.makedirs("synthetic_transcripts", exist_ok=True)
    
    print("Starting Synthetic Transcript Generation...")
    
    for scenario in SCENARIOS:
        print(f"Generating {scenario['filename']}...")
        
        prompt = (
            f"Generate a transcript for debtor {scenario['account']} "
            f"with a true balance of {scenario['balance']}. "
            f"The collector is {scenario['agent']}.\n\n"
            f"SCENARIO INSTRUCTIONS:\n{scenario['instructions']}"
        )
        
        try:
            response = llm_client.chat.completions.create(
                model=VERIFIER_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=2500
            )
            
            transcript_text = response.choices[0].message.content.strip()
            
            filepath = os.path.join("synthetic_transcripts", scenario["filename"])
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(transcript_text)
                
            print(f"✅ Saved to {filepath}\n")
            time.sleep(1) # Rate limit padding
            
        except Exception as e:
            print(f"❌ Failed to generate {scenario['filename']}: {e}")

if __name__ == "__main__":
    generate_all()