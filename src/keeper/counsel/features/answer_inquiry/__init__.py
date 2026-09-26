"""The answer_inquiry slice, re-exported so callers read `.bind`."""

from keeper.counsel.features.answer_inquiry.command import AnswerInquiry
from keeper.counsel.features.answer_inquiry.decider import decide
from keeper.counsel.features.answer_inquiry.handler import Handler, bind
from keeper.counsel.features.answer_inquiry.route import router

__all__ = ["AnswerInquiry", "Handler", "bind", "decide", "router"]
