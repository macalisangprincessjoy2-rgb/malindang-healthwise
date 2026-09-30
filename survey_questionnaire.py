RESPONDENT_TYPES = (
    ('resident', 'Residente'),
    ('bhw', 'Trabahante sa Panglawas sa Barangay (BHW)'),
    ('healthcare_professional', 'Propesyonal sa Panglawas'),
)

SEX_OPTIONS = ('Male', 'Female')

SCALE = (
    (5, 'Hugot nga mouyon', 'Labing madawat'),
    (4, 'Mouyon', 'Madawat'),
    (3, 'Walay dapig', 'Medyo madawat'),
    (2, 'Dili mouyon', 'Dili kaayo madawat'),
    (1, 'Hugot nga dili mouyon', 'Dili madawat'),
)

QUESTION_SECTIONS = (
    {
        'code': 'usability',
        'title': 'Bahin II-A. Kasayon sa Paggamit',
        'questions': (
            ('U1', 'Sayon gamiton ug sundon ang mga lakang niini nga sistema.'),
            ('U2', 'Klaro ug hapsay ang porma ug disenyo sa sistema.'),
            ('U3', 'Sayon nako maipasulod ang akong mga sintomas gamit ang Binisaya.'),
            ('U4', 'Sayon sabton ang mga panudlo nga gihatag sa sistema.'),
            ('U5', 'Makahuman ko sa pagtimbang sa kahimtang sa panglawas nga walay tabang gikan sa uban.'),
            ('U6', 'Dali motubag ang sistema sa akong mga gisulod ug gibuhat.'),
            ('U7', 'Sayon mailhan ug gamiton ang mga buton ug bahin niini.'),
            ('U8', 'Sa kinatibuk-an, kontento ko sa pagkadisenyo ug pagkapagamit sa sistema.'),
        ),
    },
    {
        'code': 'accuracy',
        'title': 'Bahin II-B. Pagkatukma',
        'questions': (
            ('A1', 'Husto nga mailhan sa sistema ang mga sintomas nga akong gisulod.'),
            ('A2', 'Motakdo sa akong gihulagway nga mga sintomas ang mga posibleng sakit nga gipakita sa sistema.'),
            ('A3', 'Ang lebel sa risgo (ubos, tunga-tunga, o grabe) nga gihatag sa sistema angay sa akong kahimtang.'),
            ('A4', 'Ang mga tambag panglawas nga gihatag sa sistema angay sa kahimtang nga gitimbang niini.'),
            ('A5', 'Ang pasilidad panglawas nga gisugyot alang sa pagpa-check angay sa akong panginahanglan.'),
            ('A6', 'Managsama ang resulta sa sistema kon isulod pag-usab ang samang mga sintomas.'),
            ('A7', 'Klaro ug masabtan ang mga pagpasabot sa sistema bahin sa pagtimbang niini.'),
            ('A8', 'Sa kinatibuk-an, mosalig ko sa katukma sa pasiunang pagtimbang sa panglawas nga gihimo sa sistema.'),
        ),
    },
    {
        'code': 'accessibility',
        'title': 'Bahin II-C. Kasayon sa Pag-abot ug Paggamit',
        'questions': (
            ('C1', 'Maabli ug magamit nako ang sistema pinaagi sa akong cellphone o tablet.'),
            ('C2', 'Matarong gihapon ang dagan sa sistema bisan hinay o limitado ang internet.'),
            ('C3', 'Sayon sabton ang Binisaya nga gigamit sa sistema.'),
            ('C4', 'Magamit nako ang sistema nga dili kinahanglan ug espesyal nga kahibalo o pagbansay sa teknolohiya.'),
            ('C5', 'Sayon pangitaon ug gamiton ang mga impormasyon bahin sa pasilidad (lokasyon, gilay-on, ug mga direksyon).'),
            ('C6', 'Magamit ang sistema bisan asa ko dapit sulod sa barangay.'),
            ('C7', 'Makaya ra nako ang gasto sa paggamit sa sistema (sama sa mobile data o load).'),
            ('C8', 'Sa kinatibuk-an, dali maabtan ug magamit sa mga residente ug trabahante sa panglawas sa among komunidad ang sistema.'),
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
