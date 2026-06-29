"""모든 ORM 모델을 한곳에서 import 한다.

이유:
- Relationship(back_populates=...) 은 "EvaluationResult" 같은 '문자열'로
  대상 클래스를 가리키고, SQLAlchemy 는 매퍼 구성 시점에 레지스트리에서
  이름으로 해석한다.
- 해당 클래스가 정의된 모듈이 한 번도 import 되지 않으면 레지스트리에 없어
  'failed to locate a name' 에러가 난다.
- 따라서 `import diag_project.models` 한 번으로 22개 테이블 클래스가 모두
  메모리에 올라오도록, 여기서 전부 import 한다.

순환 참조 주의:
- 모델 간 상호 참조는 모두 문자열(Relationship("Foo")) + TYPE_CHECKING 가드로
  처리돼 있어, 모듈 로드 시점에 다른 모델을 런타임 import 하지 않는다.
  그래서 아래 import 순서와 무관하게 순환 import 가 발생하지 않는다.
"""

from diag_project.models.group import Group
from diag_project.models.participant import Participant
from diag_project.models.coach import Coach
from diag_project.models.coach_persona import CoachPersona
from diag_project.models.competency_indicator import Competency, Indicator
from diag_project.models.question_category import QuestionCategory
from diag_project.models.diagnosis_template import DiagnosisTemplate
from diag_project.models.diagnosis_question import DiagnosisQuestion, QuestionChoice
from diag_project.models.diagnosis import Diagnosis
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.session import Session
from diag_project.models.event import Event
from diag_project.models.message import Message
from diag_project.models.participant_answer import ParticipantAnswer
from diag_project.models.question_answer import QuestionAnswer
from diag_project.models.evaluation_result import EvaluationResult
from diag_project.models.diagnosis_feedback import DiagnosisFeedback
from diag_project.models.diagnosis_result import DiagnosisResult
from diag_project.models.diagnosis_report import DiagnosisReport

__all__ = [
    "Group",
    "Participant",
    "Coach",
    "CoachPersona",
    "Competency",
    "Indicator",
    "QuestionCategory",
    "DiagnosisTemplate",
    "DiagnosisQuestion",
    "QuestionChoice",
    "Diagnosis",
    "DiagnosisSession",
    "ChatMessage",
    "Session",
    "Event",
    "Message",
    "ParticipantAnswer",
    "QuestionAnswer",
    "EvaluationResult",
    "DiagnosisFeedback",
    "DiagnosisResult",
    "DiagnosisReport",
]
