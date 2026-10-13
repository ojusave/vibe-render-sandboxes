"""A deliberately incomplete median calculation for the plugin's repair exercise."""


# The middle value should summarize a list without changing the caller's original list.
def median(values):
    """Return the middle value. The live exercise fixes even lists and empty input."""
    values.sort()
    return values[len(values) // 2]
