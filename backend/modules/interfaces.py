from abc import abstractmethod


class EventListenerMixin:
    @abstractmethod
    def _setup_event_listeners(self):
        pass


class ShutdownMixin:
    @abstractmethod
    def shutdown(self):
        pass


class Manager(EventListenerMixin, ShutdownMixin):
    pass