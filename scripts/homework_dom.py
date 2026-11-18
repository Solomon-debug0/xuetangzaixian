"""Shared selectors for the two homework player shells.

Older course pages mount the exercise component on ``.courseActionExamine``.
Current pages use ``.courseActionExamineLearnSpace`` for the same Vue data and
the same child markup.  Compose selectors with ``:is(...)`` so that a suffix
still applies to whichever shell is present.
"""

HOMEWORK_ROOT = ':is(.courseActionExamine, .courseActionExamineLearnSpace)'
HOMEWORK_QUESTION = f'{HOMEWORK_ROOT} .question'
