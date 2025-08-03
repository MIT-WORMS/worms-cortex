from abc import ABC

from launch.event import Event


class RawPayload(Event, ABC):
    """
    Client-side event for a piped process to generate arbitrary output. Should be
    inherited from and serialized with `SerializedEvent` before being transmitted.
    """

    name = "worms_cortex.events.RawPayload"
