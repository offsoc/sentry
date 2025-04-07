from __future__ import annotations

from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar
from unittest import mock
from unittest.mock import MagicMock

# TODO: Once we're on python 3.12, we can get rid of these and change the first line of the
# signature of `capture_results` to
#   def capture_results[T, **P](
P = ParamSpec("P")
T = TypeVar("T")


def capture_results(
    fn: Callable[P, T],
    results: list[T] | dict[str, list[T]],
) -> Callable[P, T]:
    """
    Create a wrapped version of the given function, which stores the return value or the error
    raised each time that function is called. This is useful when you want to spy on a given
    function and make assertions based on what it returns or raises.

    Note that in cases where the wrapped function raises, this doesn't prevent it from raising. It
    just records the error before it's raised.

    In a test, this can be used in concert with a patching context manager to record the results of
    a single function in a list:

        from unittest import mock
        from wherever import capture_results
        from animals import a_function_that_calls_get_dog, get_dog

        def test_getting_dog():
            get_dog_return_values = []
            wrapped_get_dog = capture_results(
                get_dog, get_dog_return_values
            )

            with mock.patch(
                "animals.get_dog", wraps=wrapped_get_dog
            ) as get_dog_spy:
                a_function_that_calls_get_dog()
                assert get_dog_spy.call_count == 1
                assert get_dog_return_values[0] == "maisey"

    Alternatively, if you're planning to patch more than one function, you can pass a
    dictionary:

        from unittest import mock
        from wherever import capture_results
        from animals import (
            a_function_that_calls_get_dog,
            a_function_that_calls_get_cat,
            get_dog,
            get_cat
        )

        def test_getting_animals():
            return_values = {}
            wrapped_get_dog = capture_results(
                get_dog, return_values
            )
            wrapped_get_cat = capture_results(
                get_cat, return_values
            )

            with(
                mock.patch(
                    "animals.get_dog", wraps=wrapped_get_dog
                ) as get_dog_spy,
                mock.patch(
                    "animals.get_cat", wraps=wrapped_get_cat
                ) as get_cat_spy,
            ):
                a_function_that_calls_get_dog()
                assert get_dog_spy.call_count == 1
                assert return_values["get_dog"][0] == "charlie"

                a_function_that_calls_get_cat()
                assert get_cat_spy.call_count == 1
                assert return_values["get_cat"][0] == "piper"

    Finally, if you want to record the error which was raised by a function, you can do that, too.
    This is most useful when you want to test an error which gets caught before it can be recorded
    by pytest. (If it bubbles up without getting caught, you can just use `pytest.raises`.):

        from unittest import mock
        from wherever import capture_results
        from animals import a_function_that_calls_erroring_get_dog, erroring_get_dog

        def test_getting_dog_with_error():
            erroring_get_dog_return_values = []
            wrapped_erroring_get_dog = capture_results(
                erroring_get_dog, erroring_get_dog_return_values
            )

            with mock.patch(
                "animals.erroring_get_dog", wraps=wrapped_erroring_get_dog
            ) as erroring_get_dog_spy:
                a_function_that_calls_erroring_get_dog()

                assert erroring_get_dog_spy.call_count == 1

                # Need to use `repr` since even identical errors don't count as equal
                result = erroring_get_dog_return_values[0]
                assert repr(result)== "TypeError('Expected dog, but got cat instead.')"
    """

    def record_result(result):
        if isinstance(results, list):
            results.append(result)
        elif isinstance(results, dict):
            results.setdefault(fn.__name__, []).append(result)

    def wrapped_fn(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            returned_value = fn(*args, **kwargs)
        except Exception as e:
            record_result(e)
            raise

        record_result(returned_value)
        return returned_value

    return wrapped_fn


def filter_mock_calls(
    mock_fn: MagicMock,
    args_to_match: list[Any] | list[tuple[int, Any]] | None = None,
    kwargs_to_match: dict[str, Any] | None = None,
) -> list[mock._Call]:
    """
    Given a mock function, grab only the calls whose args and/or kwargs match (or are a super set
    of) those given.

    `args_to_match` can be given as a simple list of argument values - in which case that list will
    be matched against the full list of positional arguments - or as a list of tuples of the form
    (arg_position, arg_value). (For example, if the function being mocked has the signature `f(a, b,
    c)`, to match every call where `b` is "hello", the `args_to_match` value passed to this function
    should be `[(1, "hello")]`.)

    `kwargs_to_match` should be given as a dictionary.
    """

    def _call_matches(call: mock._Call, args_to_match, kwargs_to_match):
        args_match = (
            # Use a sequence type to preserver order
            tuple(args_to_match) == call.args
            or
            # Here we can use a set because the indices are embedded in the data we're comparing
            set(args_to_match) <= set(enumerate(call.args))
        )
        kwargs_match = set(kwargs_to_match.items()) <= set(call.kwargs.items())
        return args_match and kwargs_match

    return [
        call
        for call in mock_fn.call_args_list
        if _call_matches(call, args_to_match, kwargs_to_match)
    ]
