from _salt_engine import replay

class VerificationResult:
    def __init__(self): self.violations=[]
    @property
    def valid(self): return not self.violations


def verify(solution,testdata):
    result=VerificationResult()
    try:
        replay(solution,testdata,require_complete=False)
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        text=str(exc);rule=text.split(':',1)[0]
        result.violations.append((rule if rule.startswith('H') else 'H0',text))
    return result
