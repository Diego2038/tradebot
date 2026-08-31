import pytest

from app.services.execution.errors import ExecutionError, InvalidLevelError


def test_invalid_level_error_is_subclass_of_execution_error_and_value_error():
    assert issubclass(InvalidLevelError, ExecutionError)
    assert issubclass(InvalidLevelError, ValueError)


def test_invalid_level_error_can_be_raised_and_caught_as_value_error():
    with pytest.raises(ValueError):
        raise InvalidLevelError("stop_loss >= entry_price")

    with pytest.raises(ExecutionError):
        raise InvalidLevelError("take_profit <= entry_price")
