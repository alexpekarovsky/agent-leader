"""
In-memory game data model for Agatha-style murder mystery.
"""

SUSPECTS = [
    {
        "id": "lady_blackwood",
        "name": "Lady Cordelia Blackwood",
        "description": "The elegant hostess of Blackwood Manor",
        "alibi": "Claims she was in the library reading",
        "secret": "Was having a secret affair with the victim"
    },
    {
        "id": "dr_hartley",
        "name": "Dr. Edmund Hartley",
        "description": "The family physician with a mysterious past",
        "alibi": "Says he was in his study preparing medicine",
        "secret": "The victim knew about his medical malpractice"
    },
    {
        "id": "butler_james",
        "name": "James the Butler",
        "description": "The stoic butler who's served the family for decades",
        "alibi": "Was polishing silver in the pantry",
        "secret": "Overheard the victim's plan to sell the manor"
    },
    {
        "id": "miss_winters",
        "name": "Miss Victoria Winters",
        "description": "The young governess with a troubled expression",
        "alibi": "Claims she was teaching in the nursery",
        "secret": "The victim was blackmailing her about her past"
    }
]

CLUES = [
    {
        "id": "poison_vial",
        "name": "Empty Poison Vial",
        "description": "Found in the study, labeled with Dr. Hartley's pharmacy",
        "location": "study",
        "discovered": False
    },
    {
        "id": "torn_letter",
        "name": "Torn Love Letter",
        "description": "A passionate letter torn to pieces, signed 'C.B.'",
        "location": "victim_room",
        "discovered": False
    },
    {
        "id": "muddy_footprints",
        "name": "Muddy Footprints",
        "description": "Fresh footprints leading from the garden to the study",
        "location": "hallway",
        "discovered": False
    },
    {
        "id": "blackmail_note",
        "name": "Blackmail Note",
        "description": "A threatening note demanding money, unsigned",
        "location": "victim_desk",
        "discovered": False
    }
]

LOCATIONS = [
    {
        "id": "study",
        "name": "The Study",
        "description": "Lord Blackwood's private study. Books line the walls and a half-empty glass sits on the desk.",
        "clue_ids": ["poison_vial"]
    },
    {
        "id": "victim_room",
        "name": "The Victim's Bedroom",
        "description": "An ornate bedroom with personal effects scattered about. The bed is still made.",
        "clue_ids": ["torn_letter"]
    },
    {
        "id": "hallway",
        "name": "The Grand Hallway",
        "description": "A long corridor connecting the manor's wings. The marble floor shows signs of recent traffic.",
        "clue_ids": ["muddy_footprints"]
    },
    {
        "id": "victim_desk",
        "name": "The Writing Desk",
        "description": "A cluttered writing desk in the corner of the drawing room, piled with correspondence.",
        "clue_ids": ["blackmail_note"]
    },
    {
        "id": "garden",
        "name": "The Garden",
        "description": "A manicured garden with a gate leading to the road. The soil is damp from recent rain.",
        "clue_ids": []
    },
    {
        "id": "pantry",
        "name": "The Pantry",
        "description": "Rows of polished silver and fine china. A cloth and polish sit on the counter.",
        "clue_ids": []
    }
]

CASE_INFO = {
    "victim": "Lord Reginald Blackwood",
    "location": "Blackwood Manor Study",
    "cause_of_death": "Poisoning",
    "time_of_death": "Between 9 PM and 10 PM",
    "culprit": "dr_hartley"  # The correct answer
}

# Pressure clock settings
PRESSURE_CLOCK = {
    "initial": 10,       # Total actions before time runs out
    "warning": 3,        # Actions remaining when warning triggers
    "cost_search": 1,    # Cost per location search
    "cost_interrogate": 2,  # Cost per interrogation
}

# Game phases
PHASE_INVESTIGATION = "investigation"
PHASE_ACCUSATION = "accusation"
PHASE_COMPLETE = "complete"
