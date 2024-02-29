"""Define a dummy context manager to use when tqdm is disabled."""


class DummyTqdm:
    """
    A dummy context manager that provides a no-operation replacement for tqdm.

    This class is intended to be used as a drop-in replacement for tqdm progress
    bars when the display of progress is not needed. It implements the same methods
    as tqdm, but each method performs no action.

    :param *args: Arbitrary positional arguments.
    :param **kwargs: Arbitrary keyword arguments.
    """  # noqa: D203

    def __init__(self, *args, **kwargs):
        """
        Initialize the DummyTqdm object.

        Accepts any arguments to match the tqdm interface but does nothing with them.

        :param *args: Arbitrary positional arguments.
        :param **kwargs: Arbitrary keyword arguments.
        """
        pass

    def update(self, n=1):
        """
        No-op implementation of the tqdm update method.

        Intended to be called with an increment, but ignores it.

        :param n: The increment by which to update the progress (default is 1).
        :type n: int, optional
        """
        pass

    def set_description(self, desc=None):
        """
        No-op implementation of the tqdm set_description method.

        Sets the description of the progress bar, but here it does nothing.

        :param desc: The description text for the progress bar.
        :type desc: str, optional
        """
        pass

    def __enter__(self):
        """
        Enter the runtime context related to this object.

        The 'with' statement will bind this method's return value to the target specified
        in the 'as' clause of the statement.

        :return: The current DummyTqdm instance.
        :rtype: DummyTqdm
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Exit the runtime context and perform any necessary cleanup.

        This method does not perform any exception handling or cleanup.

        :param exc_type: The type of the exception (if any occurred).
        :param exc_value: The exception instance (if any occurred).
        :param traceback: The traceback object (if any occurred).
        """
        pass
