RESPONDENT_TYPES = (
    ('resident', 'Resident'),
    ('bhw', 'Barangay Health Worker (BHW)'),
    ('healthcare_professional', 'Healthcare Professional'),
)

SEX_OPTIONS = ('Male', 'Female')

SCALE = (
    (5, 'Strongly Agree', 'Highly Acceptable'),
    (4, 'Agree', 'Acceptable'),
    (3, 'Neutral', 'Moderately Acceptable'),
    (2, 'Disagree', 'Less Acceptable'),
    (1, 'Strongly Disagree', 'Not Acceptable'),
)

QUESTION_SECTIONS = (
    {
        'code': 'usability',
        'title': 'Part II-A. Usability',
        'questions': (
            ('U1', 'The system is easy to navigate and use.'),
            ('U2', 'The layout and design of the system are clear and organized.'),
            ('U3', 'I can easily enter my symptoms in the Bisaya language.'),
            ('U4', 'The instructions provided by the system are easy to understand.'),
            ('U5', 'I can complete a health assessment without needing outside help.'),
            ('U6', 'The system responds quickly to my inputs and actions.'),
            ('U7', 'The controls and features are easy to recognize and use.'),
            ('U8', 'Overall, I am satisfied with how the system is designed to use.'),
        ),
    },
    {
        'code': 'accuracy',
        'title': 'Part II-B. Accuracy',
        'questions': (
            ('A1', 'The system correctly identifies the symptoms I entered.'),
            ('A2', 'The possible health conditions shown by the system match my described symptoms.'),
            ('A3', 'The risk level (Mild, Moderate, or Severe) given by the system is appropriate to my condition.'),
            ('A4', 'The health recommendations provided by the system are relevant to my assessed condition.'),
            ('A5', 'The healthcare facility suggested for referral is appropriate to my needs.'),
            ('A6', 'The system provides consistent results when the same symptoms are entered again.'),
            ('A7', 'The explanations given by the system for its assessment are clear and understandable.'),
            ('A8', 'Overall, I trust the accuracy of the system’s preliminary health assessment.'),
        ),
    },
    {
        'code': 'accessibility',
        'title': 'Part II-C. Accessibility',
        'questions': (
            ('C1', 'I can access the system using my mobile phone or tablet device.'),
            ('C2', 'The system works properly even with a slow or limited internet connection.'),
            ('C3', 'The Bisaya language used in the system is easy for me to understand.'),
            ('C4', 'I can use the system without needing special technical skills or training.'),
            ('C5', 'The information provided (facility location, distance, directions) is easy to find and use.'),
            ('C6', 'The system is usable regardless of my location within the barangay.'),
            ('C7', 'The cost of using the system (e.g., mobile data or load) is manageable for me.'),
            ('C8', 'Overall, the system is accessible to residents and health workers in our community.'),
        ),
    },
)

QUESTIONNAIRE = tuple(
    (code, statement, section['title'])
    for section in QUESTION_SECTIONS
    for code, statement in section['questions']
)
QUESTION_CODES = tuple(code for code, _, _ in QUESTIONNAIRE)
RESPONDENT_GOAL = 386
