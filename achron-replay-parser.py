#!/usr/bin/env python

import struct
from optparse import OptionParser


def enum(*sequential, **named):
    enums = dict(zip(sequential, range(len(sequential))), **named)
    reverse = dict((value, key) for key, value in enums.items())
    enums['reverse_mapping'] = reverse
    return type('Enum', (), enums)


def _unpack_bitmask(value, length):
    return [bool(value & (1 << x)) for x in range(length - 1)]


def _read_length_prefixed_field(len_type, data, offset=0):
    length, = struct.unpack_from("<" + len_type, data, offset)
    offset += struct.calcsize("<" + len_type)
    return data[offset:offset + length], offset + length


def _read_string(len_type, data, offset=0):
    data, offset = _read_length_prefixed_field(len_type, data, offset)
    return data.decode('ascii'), offset

GAME_TICKS_PER_SECOND = 18


def format_timestamp(ticks):
    minutes, ticks = divmod(ticks, GAME_TICKS_PER_SECOND * 60)
    seconds, ticks = divmod(ticks, GAME_TICKS_PER_SECOND)
    return "%3dm %2ds %2dt" % (minutes, seconds, ticks)

MessageType = enum(
    "NO_MESSAGE",
    "MESSAGE",
    "NEW_CLIENT",
    "NEW_BANNED_CLIENT",
    "DISCONNECTED",
    "ERROR"
)

MessageContentType = enum(
    SET_CONFIGURATION_PARAMETER=7,
    CHRONAL_COMMANDS=16,
    SEND_TEXT=32,
    BROADCAST_TEXT=33,
    UNPAUSE_ENGINE=37,
    PAUSE_ENGINE=38,
    SAVE_GAME=40,
    SURRENDER=41,
    GLOBAL_TIME_RATE_CHANGE_REQUEST=71
)

CommandType = enum(
    "MOVE_TIME_POSITION",
    "FOLLOW_TO_TIME",
    "ASSIGN_UNIT_OBJECTIVE",
    "ASSIGN_UNIT_OBJECTIVE_ONLY",
    "MARK_UNIT",
    "DELETE_EVENTS",
    "SET_BOOKMARK",
    "JUMP_TO_BOOKMARK",
    "CREATE_ALLIANCE",
    "BREAK_ALLIANCE",
    "GIVE_VISIBILITY_TO_PLAYER",
    "REVOKE_VISIBILITY_FROM_PLAYER",
    "GIVE_COMMAND_ABILITY_TO_PLAYER",
    "REVOKE_COMMAND_ABILITY_FROM_PLAYER",
    "FAST_TIME",
    "SLOW_TIME",
    "STOP_TIME",
    "NORMAL_TIME",
    "DEBUG_RELOAD_SCRIPTS",
    "DELETE_NEXT_COMMAND_AND_JUMP_TO_TIME"
)


class Player(object):
    def __init__(self, seat, name):
        self.seat = seat
        self.name = name
        self.time_position = 0
        self._last_timestamp = 0
        self._time_speed_factor = 1

    def _update_timestamp(self, timestamp):
        delta_game_ticks = (timestamp - self._last_timestamp) / 2.0
        self.time_position += int(delta_game_ticks * self._time_speed_factor)
        self._last_timestamp = timestamp

    def __str__(self):
        return "%s (player %d)" % (self.name, self.seat)

# Seems to be the player number for non-player-specific messages.
NONE_PLAYER = 255

class BaseReplayMessage(object):
    """Parent class of all replay messages."""
    def __init__(self, timestamp, message, player, data):
        self.timestamp = timestamp
        if player == NONE_PLAYER:
            self.player = None
        else:
            player._update_timestamp(timestamp)
            self.player = player


class NetworkMessage(BaseReplayMessage):
    """Parent class of all network-related replay messages."""
    pass


class NoOpMessage(NetworkMessage):
    def __init__(self, timestamp, message, player, data):
        self.timestamp = timestamp

    def __str__(self):
        return "Nothing happens"


class NewClientMessage(NetworkMessage):
    def __init__(self, timestamp, message, player, data):
        # Edited replays will contain joins by the observer (who may have been
        # a participant in the replay), so player may already be an instance
        # of Player.
        if not isinstance(player, Player):
            player = Player(player, data.decode('ascii'))
        super(NewClientMessage, self).__init__(timestamp, message, player, data)

    def __str__(self):
        return "%s joined" % self.player


class NewBannedClientMessage(NetworkMessage):
    def __init__(self, timestamp, message, player, data):
        self.player = player = Player(player, data.decode('ascii'))
        super(NewBannedClientMessage, self).__init__(timestamp, message, player, data)

    def __str__(self):
        return "%s attempts to join, but was previously banned" % self.player


class DisconnectedMessage(NetworkMessage):
    def __str__(self):
        return "%s disconnects" % self.player


class ErrorMessage(NetworkMessage):
    def __str__(self):
        return "An error occurred"


class GameMessage(BaseReplayMessage):
    """Parent class of all game-related replay messages."""


class ChatMessage(GameMessage):
    pass


class PrivateChatMessage(ChatMessage):
    def __init__(self, timestamp, message, player, data):
        super(PrivateChatMessage, self).__init__(timestamp, message, player, data)
        self.recipient = struct.unpack_from("<B", data)
        self.contents = data[1:].decode('ascii').strip()

    def __str__(self):
        return "%s whispers to %s: %s" % (self.player, self.recipient,
                                          self.contents)


class PublicChatMessage(ChatMessage):
    def __init__(self, timestamp, message, player, data):
        super(PublicChatMessage, self).__init__(timestamp, message, player, data)
        self.contents = data.decode('ascii').strip()

    def __str__(self):
        return "%s says: %s" % (self.player, self.contents)


class UnpauseEngine(GameMessage):
    def __str__(self):
        return "%s unpauses the game" % self.player


class PauseEngine(GameMessage):
    def __str__(self):
        return "%s pauses the game" % self.player


class SaveGame(GameMessage):
    def __str__(self):
        return "%s saves the game" % self.player


class PlayerSurrender(GameMessage):
    def __str__(self):
        return "%s surrenders" % self.player


class GlobalTimeRateChange(GameMessage):
    def __init__(self, timestamp, message, player, data):
        super(GlobalTimeRateChange, self).__init__(timestamp, message, player, data)
        self.rate, = struct.unpack("<f", data)

    def __str__(self):
        return "%s changes the global time rate to %s" % (self.player, self.rate)


# Commands

class BaseCommand(GameMessage):
    _data_struct = struct.Struct("<")


class MoveTimePosition(BaseCommand):
    def __init__(self, timestamp, message, player, data):
        super(MoveTimePosition, self).__init__(timestamp, message, player, data)
        self.target_time, = struct.unpack("<I", data)
        player.time_position = self.target_time

    def __str__(self):
        return "%s jumps to time %s" % (self.player,
                format_timestamp(self.target_time))

objectives = {0: [['Defend', 'NO_PARAMETER'], ['Idle', 'NO_PARAMETER']], 1: [['Move', 'POSITION'], ['display waypoint', 'POSITION'], ['New (Down)', 'NO_PARAMETER'], ['Attack Unit', 'UNIT'], ['Processing', 'NO_PARAMETER'], ['Build MFB', 'NO_PARAMETER'], ['Build Tornade', 'NO_PARAMETER']], 2: [['Attack', 'POSITION_OR_UNIT'], ['New (Up)', 'NO_PARAMETER'], ['Process Resource', 'UNIT'], ['Process Resources', 'UNIT'], ['Build Frigate', 'NO_PARAMETER'], ['Create Marines', 'NO_PARAMETER'], ['Build Mech', 'NO_PARAMETER']], 3: [['Patrol', 'POSITION_OR_UNIT'], ['New (Down Left)', 'NO_PARAMETER'], ['Make Octo', 'NO_PARAMETER'], ['Build MFB', 'NO_PARAMETER'], ['Create SOPs', 'NO_PARAMETER'], ['Build ATHC', 'NO_PARAMETER']], 4: [['Attack Unit', 'UNIT'], ['New (Down Right)', 'NO_PARAMETER'], ['Make Sepi', 'NO_PARAMETER'], ['Turn AutoCommand ON', 'NO_PARAMETER'], ['Turn Auto Hierarchy ON', 'NO_PARAMETER'], ['Build Blackbird', 'NO_PARAMETER'], ['Build Lancer', 'NO_PARAMETER']], 5: [['New (Up Left)', 'NO_PARAMETER'], ['Make Pharo', 'NO_PARAMETER'], ['Turn Smart Idle ON', 'NO_PARAMETER'], ['Build Heavy Cruiser', 'NO_PARAMETER'], ['Build Tornade', 'NO_PARAMETER']], 6: [['New (Up Right)', 'NO_PARAMETER'], ['Turn AutoCommand OFF', 'NO_PARAMETER'], ['Turn Auto Hierarchy OFF', 'NO_PARAMETER'], ['Build MAR Tank', 'NO_PARAMETER'], ['Build Tank', 'NO_PARAMETER']], 7: [['Turn Smart Idle OFF', 'NO_PARAMETER'], ['Build Heavy Cruiser', 'NO_PARAMETER'], ['Build Tank', 'NO_PARAMETER']], 8: [['Change Commander', 'UNIT'], ['Relocate', 'NO_PARAMETER'], ['Attack', 'UNIT'], ['Build Blackbird', 'NO_PARAMETER'], ['Attack Unit', 'UNIT'], ['displaying waypoint', 'POSITION']], 9: [['Remove from Hierarchy', 'NO_PARAMETER'], ['Remove from Heirarchy', 'NO_PARAMETER'], ['Relocate', 'POSITION'], ['Move', 'POSITION'], ['Clear Commander', 'NO_PARAMETER']], 10: [['Priority', 'NO_PARAMETER'], ['Lead group', 'NO_PARAMETER']], 11: [['Build', 'NO_PARAMETER'], ['Load Unit', 'UNIT'], ['Nanite Infect', 'NO_PARAMETER'], ['Place buildings', 'NO_PARAMETER'], ['Merge', 'UNIT'], ['Stop and re-enable', 'NO_PARAMETER'], ['Chrono-Freeze', 'NO_PARAMETER'], ['Defend/Repel', 'NO_PARAMETER'], ['Build Foundation', 'NO_PARAMETER'], ['Build Resource Processor', 'POSITION'], ['Build Comm Hub', 'POSITION'], ['Drop Nuke Now ', 'NO_PARAMETER'], ['Resource Processor', 'POSITION'], ['Comm Jam', 'NO_PARAMETER'], ['Morph: Reaph', 'POSITION'], ['Morph: Arcticus', 'POSITION']], 12: [['Clear Nanite', 'UNIT'], ['Release Cargo', 'POSITION'], ['Build Foundation', 'NO_PARAMETER'], ['Upgrade Tank', 'NO_PARAMETER'], ['Activate', 'POSITION'], ['Merge', 'NO_PARAMETER'], ['Upgrade', 'NO_PARAMETER'], ['Temporal Soliton Shield', 'NO_PARAMETER'], ['Stop', 'POSITION'], ['Nuke a Location', 'POSITION'], ['Moving to Morph ', 'NO_PARAMETER']], 13: [['Ride in a Tank', 'NO_PARAMETER'], ['Cancel Progen for All', 'NO_PARAMETER'], ['Cancel Build', 'NO_PARAMETER'], ['Merge', 'NO_PARAMETER'], ['QPlasma -> LCrystal', 'NO_PARAMETER'], ['Clear Nanite', 'NO_PARAMETER'], ['Morph to Pharo', 'NO_PARAMETER'], ['displaying waypoint', 'POSITION']], 14: [['Cancel Build', 'NO_PARAMETER'], ['Cancel Factory/Progeneration', 'NO_PARAMETER'], ['Fix Troops', 'UNIT'], ['Cancel Make Buildings', 'NO_PARAMETER'], ['Clear Nanite', 'UNIT'], ['Fix Unit', 'UNIT'], ['Cancel Piloting', 'NO_PARAMETER'], ['Reload Nuke', 'NO_PARAMETER'], ['Cancel Progeneration', 'NO_PARAMETER']], 15: [['Recover', 'UNIT'], ['Recover Status', 'UNIT'], ['Break TSS', 'UNIT']], 16: [['Stop', 'NO_PARAMETER'], ['Chronobomb', 'POSITION'], ['Temporal Soliton Shield', 'UNIT']], 17: [['Release Unit', 'NO_PARAMETER'], ['Cloaking On', 'NO_PARAMETER'], ['Release Troop', 'NO_PARAMETER'], ['ChronoBomb', 'NO_PARAMETER'], ['Break TSS', 'UNIT'], ['Morph: Dome', 'NO_PARAMETER']], 18: [['', 'NO_PARAMETER'], ['Congregate units at', 'POSITION_OR_UNIT'], ['Plasma Bomb', 'NO_PARAMETER'], ['Congregate Units At', 'POSITION_OR_UNIT'], ['Congregate Troops At', 'POSITION_OR_UNIT'], ['Morph: Dome', 'POSITION'], ['Morph: Mound', 'POSITION']], 19: [['Clear Congregation Point', 'NO_PARAMETER'], ['', 'NO_PARAMETER'], ['Upgrade Skip-Teleport', 'NO_PARAMETER'], ['Upgrade Tank', 'NO_PARAMETER'], ['Chronobomb', 'NO_PARAMETER'], ['Upgrade Beam', 'NO_PARAMETER'], ['Repel', 'NO_PARAMETER'], ['Upgrade', 'NO_PARAMETER']], 20: [['Rally on unit', 'UNIT'], ['Uncloak', 'NO_PARAMETER'], ['Skip Torpedo', 'POSITION'], ['Nanite Infect', 'UNIT'], ['Plasma Bomb', 'POSITION'], ['Fire Charge Beam', 'UNIT'], ['Repel', 'NO_PARAMETER'], ['Chrono-Freeze ', 'NO_PARAMETER'], ['Equip Nuke', 'NO_PARAMETER'], ['Auto Slingshot', 'POSITION'], ['Defend/Repel', 'NO_PARAMETER'], ['Comm Jam', 'NO_PARAMETER']], 21: [['Teleport Self To', 'POSITION'], ['Relink (to Arcticus)', 'UNIT'], ['ChronoBomb', 'POSITION'], ['Rally on unit', 'UNIT'], ['Cancel Defend/Repel', 'NO_PARAMETER']], 22: [['Resource Processor', 'POSITION'], ['Slingshot', 'POSITION'], ['Skip Torpedo', 'NO_PARAMETER'], ['Attack Dispatch', 'POSITION_OR_UNIT'], ['Plasma Bomb', 'NO_PARAMETER'], ['Equip Nuke', 'NO_PARAMETER']], 23: [['Importer', 'POSITION'], ['Teleporter', 'POSITION'], ['Move Dispatch', 'POSITION'], ['ChronoBomb', 'NO_PARAMETER'], ['', 'NO_PARAMETER'], ['displaying waypoint', 'POSITION']], 24: [['Factory', 'POSITION'], ['Defense Turret', 'POSITION'], ['Stop Dispatch', 'NO_PARAMETER'], ['Upgrade Adv Structures', 'NO_PARAMETER'], ['Make Vehicles', 'NO_PARAMETER'], ['Upgrade Machinery', 'NO_PARAMETER'], ['Upgrade Autodefence', 'NO_PARAMETER']], 25: [['Armory', 'POSITION'], ['Macrofab', 'POSITION'], ['Chronoport Dispatch', 'TIME'], ['', 'NO_PARAMETER'], ['Make Vehicles', 'NO_PARAMETER']], 26: [['Comm Center', 'POSITION'], ['Defense Turret', 'NO_PARAMETER'], ['Make Resource Processor', 'POSITION'], ['Upgrade Loligo Class', 'NO_PARAMETER'], ['Upgrade Ground Units', 'NO_PARAMETER'], ['Research Halcyon Class', 'NO_PARAMETER']], 27: [['Slingshot', 'NO_PARAMETER'], ['Create Depot', 'NO_PARAMETER'], ['Make Mound', 'POSITION'], ['', 'NO_PARAMETER']], 28: [['Chronoporter', 'POSITION'], ['Make Reaph', 'POSITION'], ['Upgrade Specials', 'NO_PARAMETER']], 29: [['Teleporter', 'NO_PARAMETER'], ['Create Annex', 'NO_PARAMETER'], ['Make Arcticus', 'POSITION'], ['', 'NO_PARAMETER']], 30: [['Chronoporter', 'NO_PARAMETER'], ['Make Spyre', 'POSITION'], ['Upgrade Chronoporting', 'NO_PARAMETER'], ['Zayin Pulser', 'NO_PARAMETER'], ['Upgrade Gate Tech', 'NO_PARAMETER']], 31: [['Carrier', 'POSITION'], ['Make Dome', 'POSITION'], ['', 'NO_PARAMETER'], ['Teth Pulser', 'NO_PARAMETER'], ['Garguntuan', 'POSITION'], ['Spyre', 'POSITION']], 32: [['Carrier', 'NO_PARAMETER'], ['Make Dome', 'NO_PARAMETER'], ['Upgrade Weapons', 'NO_PARAMETER'], ['Shin Pulser', 'NO_PARAMETER'], ['Upgrade Aerospace', 'NO_PARAMETER'], ['Upgrade Weaponry', 'NO_PARAMETER'], ['Spyre', 'NO_PARAMETER']], 33: [['Make Spyre', 'NO_PARAMETER'], ['', 'NO_PARAMETER'], ['Zayin Tercher', 'NO_PARAMETER']], 34: [['Carry/Commander', 'UNIT'], ['Create SlipGate', 'NO_PARAMETER'], ['Chronoport Dispatch', 'NO_PARAMETER'], ['Teth Tercher', 'NO_PARAMETER']], 35: [['Factory/Progeneration', 'NO_PARAMETER'], ['Carrier', 'NO_PARAMETER'], ['Create Bastion', 'NO_PARAMETER'], ['Shin Tercher', 'NO_PARAMETER']], 36: [['Importer', 'POSITION'], ['Create Incepter', 'NO_PARAMETER'], ['Upgrade Chronoporting', 'NO_PARAMETER'], ['Zayin Halcyon', 'NO_PARAMETER'], ['Upgrade Gate Tech', 'NO_PARAMETER']], 37: [['Factory/Progeneration', 'POSITION'], ['Armory', 'POSITION'], ['Create Incepter', 'NO_PARAMETER'], ['Upgrade Chronoporting', 'NO_PARAMETER'], ['Teth Halcyon', 'NO_PARAMETER']], 38: [['Produce Octopod', 'NO_PARAMETER'], ['Upgrade Weapons', 'NO_PARAMETER'], ['Shin Halcyon', 'NO_PARAMETER'], ['Upgrade Aerospace', 'NO_PARAMETER'], ['Upgrade Weaponry', 'NO_PARAMETER'], ['Produce Octo', 'NO_PARAMETER']], 39: [['Produce Sepipod', 'NO_PARAMETER'], ['Create Incepter', 'NO_PARAMETER'], ['Upgrade Weapons', 'NO_PARAMETER'], ['', 'NO_PARAMETER'], ['Upgrade Aerospace', 'NO_PARAMETER'], ['Upgrade Weaponry', 'NO_PARAMETER'], ['Pilot Vehicle', 'NO_PARAMETER'], ['Produce Sepi', 'NO_PARAMETER']], 40: [['Produce Pharopod', 'NO_PARAMETER'], ['Upgrade Adv Structures', 'NO_PARAMETER'], ['Shin Pulser', 'NO_PARAMETER'], ['Split Down', 'NO_PARAMETER'], ['Upgrade Machinery', 'NO_PARAMETER'], ['Upgrade Autodefense', 'NO_PARAMETER'], ['Pilot Pulser', 'NO_PARAMETER'], ['Produce Pharo', 'NO_PARAMETER']], 41: [['Produce Octoligo', 'NO_PARAMETER'], ['Upgrade Specials', 'NO_PARAMETER'], ['Teth Tercher', 'NO_PARAMETER'], ['Equip Nuke', 'NO_PARAMETER'], ['Pilot Tercher', 'NO_PARAMETER'], ['Produce Octopod', 'NO_PARAMETER']], 42: [['Produce Sepiligo', 'NO_PARAMETER'], ['Upgrade Loligo Class', 'NO_PARAMETER'], ['Shin Tercher', 'NO_PARAMETER'], ['Upgrade Ground Units', 'NO_PARAMETER'], ['Research Halcyon Class', 'NO_PARAMETER'], ['Pilot Halcyon', 'NO_PARAMETER'], ['Produce Sepipod', 'NO_PARAMETER']], 43: [['Produce Pharoligo', 'NO_PARAMETER'], ['Zayin Halcyon', 'NO_PARAMETER'], ['Create Marines', 'NO_PARAMETER'], ['Create Zayin Vir', 'NO_PARAMETER'], ['Pilot Halcyon', 'NO_PARAMETER'], ['Produce Pharopod', 'NO_PARAMETER']], 44: [['Octopod', 'NO_PARAMETER'], ['Teth Halcyon', 'NO_PARAMETER'], ['Create SOPs', 'NO_PARAMETER'], ['Create Teth Vir', 'NO_PARAMETER'], ['Octo', 'NO_PARAMETER']], 45: [['Chronoport', 'NO_PARAMETER'], ['Sepipod', 'NO_PARAMETER'], ['', 'NO_PARAMETER'], ['Shin Halcyon', 'NO_PARAMETER'], ['Create Shin Vir', 'NO_PARAMETER'], ['Sepi', 'NO_PARAMETER']], 46: [['Chronoport', 'NO_PARAMETER'], ['Pharopod', 'NO_PARAMETER'], ['Chronoport ', 'NO_PARAMETER'], ['Shin Halcyon', 'NO_PARAMETER'], ['Create Zayin Vir', 'NO_PARAMETER'], ['Pharo', 'NO_PARAMETER']], 47: [['Teleport', 'POSITION'], ['Octoligo', 'NO_PARAMETER'], ['Teleport Self To', 'POSITION'], ['Create Teth Vir', 'NO_PARAMETER'], ['Octopod', 'NO_PARAMETER']], 48: [['Chronoport', 'TIME'], ['Sepiligo', 'NO_PARAMETER'], ['Create Shin Vir', 'NO_PARAMETER'], ['Sepipod', 'NO_PARAMETER']], 49: [['Pharoligo', 'NO_PARAMETER'], ['Pharopod', 'NO_PARAMETER'], ['Pharpod', 'NO_PARAMETER']], 50: [['Teleport', 'NO_PARAMETER'], ['Octoligo', 'NO_PARAMETER'], ['', 'NO_PARAMETER'], ['Human', 'NO_PARAMETER']], 51: [['Sepiligo', 'NO_PARAMETER'], ['Grekim', 'NO_PARAMETER'], ['', 'NO_PARAMETER']], 52: [['Pharoligo', 'NO_PARAMETER'], ['Vecgir', 'NO_PARAMETER'], ['Upgrade Power', 'NO_PARAMETER'], ['Octo Resource Processor', 'POSITION']], 53: [['Sepiligo', 'NO_PARAMETER'], ['Random', 'NO_PARAMETER'], ['Upgrade Power', 'NO_PARAMETER']], 54: [['Pharoligo', 'NO_PARAMETER'], ['Upgrade Power', 'NO_PARAMETER']], 55: [['Sepipod', 'NO_PARAMETER']], 56: [['Pharopod', 'NO_PARAMETER']], 57: [['Create Slipgate', 'NO_PARAMETER']], 58: [['Create Bastion', 'NO_PARAMETER']], 59: [['Create ACC', 'NO_PARAMETER']]}


def _lower_bitmask(n):
    bitmask = 0
    for i in range(n):
        bitmask |= 1 << i
    return bitmask


def _get_objective(number, parameter=None):
    candidates = objectives[number]

    if parameter is None:
        return [c[0] for c in candidates if c[1] == 'NO_PARAMETER']
    else:
        return [c[0] for c in candidates if c[1] != 'NO_PARAMETER']


class AssignUnitObjective(BaseCommand):
    _data_struct = struct.Struct("<HBI")

    def __init__(self, timestamp, message, player, data):
        super(AssignUnitObjective, self).__init__(timestamp, message, player, data)
        self.unit, objective, self.parameter = AssignUnitObjective._data_struct.unpack_from(data)
        self.objective = objective & _lower_bitmask(6)
        self.queued = bool(objective & (1 << 7))

    def __str__(self):
        method = "assigns"
        if self.queued:
            method = "queued"

        return "%s %s unit %d objective %d (one of %s)" % (self.player, method,
            self.unit, self.objective, ', '.join(_get_objective(self.objective, self.parameter)))


class AssignUnitObjectiveOnly(BaseCommand):
    _data_struct = struct.Struct("<HB")

    def __init__(self, timestamp, message, player, data):
        super(AssignUnitObjectiveOnly, self).__init__(timestamp, message, player, data)
        self.unit, objective = AssignUnitObjectiveOnly._data_struct.unpack_from(data)
        self.objective = objective & _lower_bitmask(6)
        self.queued = bool(objective & (1 << 7))

    def __str__(self):
        method = "assigns"
        if self.queued:
            method = "queued"

        return "%s %s unit %d objective %d (one of %s)" % (self.player, method,
            self.unit, self.objective, ', '.join(_get_objective(self.objective)))


class MarkUnit(BaseCommand):
    _data_struct = struct.Struct("<H")

    def __init__(self, timestamp, message, player, data):
        super(MarkUnit, self).__init__(timestamp, message, player, data)
        self.unit, = MarkUnit._data_struct.unpack(data)

    def __str__(self):
        return "%s marks unit %d" % (self.player, self.unit)


class UndoForUnit(BaseCommand):
    _data_struct = struct.Struct("<HI")

    def __init__(self, timestamp, message, player, data):
        super(UndoForUnit, self).__init__(timestamp, message, player, data)
        self.unit, self.end_time = UndoForUnit._data_struct.unpack_from(data)
        self.start_time = self.player.time_position

    def __str__(self):
        return "%s undoes all orders for %d from (%s) to (%s)" % (self.player,
            self.unit, format_timestamp(self.start_time),
            format_timestamp(self.end_time))


class SetBookmark(BaseCommand):
    _data_struct = struct.Struct("<B")

    def __init__(self, timestamp, message, player, data):
        super(SetBookmark, self).__init__(timestamp, message, player, data)
        self.bookmark_number, = SetBookmark._data_struct.unpack(data)

    def __str__(self):
        return "%s sets bookmark %d" % (self.player, self.bookmark_number)


class JumpToBookmark(BaseCommand):
    _data_struct = struct.Struct("<B")

    def __init__(self, timestamp, message, player, data):
        super(JumpToBookmark, self).__init__(timestamp, message, player, data)
        self.bookmark_number, = JumpToBookmark._data_struct.unpack(data)

    def __str__(self):
        return "%s jumps to bookmark %d" % (self.player, self.bookmark_number)


class CreateAlliance(BaseCommand):
    _data_struct = struct.Struct("<B")

    def __init__(self, timestamp, message, player, data):
        super(CreateAlliance, self).__init__(timestamp, message, player, data)
        self.new_ally, = CreateAlliance._data_struct.unpack(data)

    def __str__(self):
        return "%s offers alliance to %s" % (self.player, self.new_ally)


class BreakAlliance(BaseCommand):
    _data_struct = struct.Struct("<B")

    def __init__(self, timestamp, message, player, data):
        super(BreakAlliance, self).__init__(timestamp, message, player, data)
        self.former_ally, = BreakAlliance._data_struct.unpack(data)

    def __str__(self):
        return "%s breaks alliance with %s" % (self.player, self.former_ally)


class ShareVision(BaseCommand):
    _data_struct = struct.Struct("<B")

    def __init__(self, timestamp, message, player, data):
        super(ShareVision, self).__init__(timestamp, message, player, data)
        self.recipient, = ShareVision._data_struct.unpack(data)

    def __str__(self):
        return "%s shares vision with %s" % (self.player, self.recipient)


class RevokeVision(BaseCommand):
    _data_struct = struct.Struct("<B")

    def __init__(self, timestamp, message, player, data):
        super(RevokeVision, self).__init__(timestamp, message, player, data)
        self.recipient, = RevokeVision._data_struct.unpack(data)

    def __str__(self):
        return "%s stops sharing vision with %s" % (self.player, self.recipient)

class ShareControl(BaseCommand):
    _data_struct = struct.Struct("<B")

    def __init__(self, timestamp, message, player, data):
        super(ShareControl, self).__init__(timestamp, message, player, data)
        self.recipient, = ShareControl._data_struct.unpack(data)

    def __str__(self):
        return "%s shares unit control with %s" % (self.player, self.recipient)


class RevokeControl(BaseCommand):
    _data_struct = struct.Struct("<B")

    def __init__(self, timestamp, message, player, data):
        super(RevokeControl, self).__init__(timestamp, message, player, data)
        self.recipient, = RevokeControl._data_struct.unpack(data)

    def __str__(self):
        return "%s stops sharing unit control with %s" % (self.player, self.recipient)


class SwitchFastForward(BaseCommand):
    def __init__(self, timestamp, message, player, data):
        super(SwitchFastForward, self).__init__(timestamp, message, player, data)
        self.player._time_speed_factor = 2

    def __str__(self):
        return "%s switches to fast forward" % self.player


class SwitchSlowMotion(BaseCommand):
    def __init__(self, timestamp, message, player, data):
        super(SwitchSlowMotion, self).__init__(timestamp, message, player, data)
        self.player._time_speed_factor = 0.5

    def __str__(self):
        return "%s switches to slow motion" % self.player


class SwitchPause(BaseCommand):
    def __init__(self, timestamp, message, player, data):
        super(SwitchPause, self).__init__(timestamp, message, player, data)
        self.player._time_speed_factor = 0

    def __str__(self):
        return "%s pauses" % self.player


class SwitchNormalTime(BaseCommand):
    def __init__(self, timestamp, message, player, data):
        super(SwitchNormalTime, self).__init__(timestamp, message, player, data)
        self.player._time_speed_factor = 1

    def __str__(self):
        return "%s switched to normal time" % self.player


class SetConfigurationParameter(GameMessage):
    def __init__(self, timestamp, message, player, data):
        super(SetConfigurationParameter, self).__init__(timestamp, message, player, data)
        self.key, offset = _read_string("B", data)
        self.val = data[offset:].decode("ascii")

    def __str__(self):
        return "Set %s to %s" % (self.key, self.val)


class ReloadScripts(BaseCommand):
    def __init__(self, timestamp, message, player, data):
        super(ReloadScripts, self).__init__(timestamp, message, player, data)

    def __str__(self):
        return "%s reloads the scripts" % self.player


class DeleteNextCommand(BaseCommand):
    _data_struct = struct.Struct("<HB")

    def __init__(self, timestamp, message, player, data):
        super(DeleteNextCommand, self).__init__(timestamp, message, player, data)
        self.unit, self.direction = DeleteNextCommand._data_struct.unpack(data)

    def __str__(self):
        if self.direction == 1:
            return "%s jumps to it %d's next command and deletes it" % (self.player, self.unit)
        else:
            return "%s jumps to it %d's previous command and deletes it" % (self.player, self.unit)


def make_replay_message(timestamp, message_type, message, player, data):
    return {
        MessageType.NO_MESSAGE: NoOpMessage,
        MessageType.MESSAGE: make_message,
        MessageType.NEW_CLIENT: NewClientMessage,
        MessageType.NEW_BANNED_CLIENT: NewBannedClientMessage,
        MessageType.DISCONNECTED: DisconnectedMessage,
        MessageType.ERROR: ErrorMessage
    }[message_type](timestamp, message, player, data)


def make_message(timestamp, message, player, data):
    return {
        MessageContentType.CHRONAL_COMMANDS: make_command,
        MessageContentType.SEND_TEXT: PrivateChatMessage,
        MessageContentType.BROADCAST_TEXT: PublicChatMessage,
        MessageContentType.UNPAUSE_ENGINE: UnpauseEngine,
        MessageContentType.PAUSE_ENGINE: PauseEngine,
        MessageContentType.SAVE_GAME: SaveGame,
        MessageContentType.SURRENDER: PlayerSurrender,
        MessageContentType.GLOBAL_TIME_RATE_CHANGE_REQUEST: GlobalTimeRateChange,
        MessageContentType.SET_CONFIGURATION_PARAMETER: SetConfigurationParameter
    }[message](timestamp, message, player, data)


_command_struct = struct.Struct("<B")


def make_command(timestamp, message, player, data):
    command_count, = _command_struct.unpack_from(data)
    data = data[_command_struct.size:]
    results = []

    for i in range(command_count):
        command_number, = _command_struct.unpack_from(data)
        data = data[_command_struct.size:]

        command = {
            CommandType.MOVE_TIME_POSITION: MoveTimePosition,
            CommandType.FOLLOW_TO_TIME: MoveTimePosition,
            CommandType.ASSIGN_UNIT_OBJECTIVE: AssignUnitObjective,
            CommandType.ASSIGN_UNIT_OBJECTIVE_ONLY: AssignUnitObjectiveOnly,
            CommandType.MARK_UNIT: MarkUnit,
            CommandType.DELETE_EVENTS: UndoForUnit,
            CommandType.SET_BOOKMARK: SetBookmark,
            CommandType.JUMP_TO_BOOKMARK: JumpToBookmark,
            CommandType.CREATE_ALLIANCE: CreateAlliance,
            CommandType.BREAK_ALLIANCE: BreakAlliance,
            CommandType.GIVE_COMMAND_ABILITY_TO_PLAYER: ShareControl,
            CommandType.REVOKE_COMMAND_ABILITY_FROM_PLAYER: RevokeControl,
            CommandType.FAST_TIME: SwitchFastForward,
            CommandType.SLOW_TIME: SwitchSlowMotion,
            CommandType.STOP_TIME: SwitchPause,
            CommandType.NORMAL_TIME: SwitchNormalTime,
            CommandType.DEBUG_RELOAD_SCRIPTS: ReloadScripts,
            CommandType.DELETE_NEXT_COMMAND_AND_JUMP_TO_TIME: None,
        }[command_number]

        results.append(command(timestamp, message, player, data))
        data = data[command._data_struct.size:]

    return results


class Replay(object):
    _header_struct1 = struct.Struct("<5s4B")
    _header_struct2 = struct.Struct("<IH")
    _body_struct = struct.Struct("<I3B")

    def __init__(self, data):
        header = Replay._header_struct1.unpack_from(data)

        magic = header[0]
        assert(magic == b"CRRP\x00")

        self.version = header[1:5]

        self.map_path, offset = _read_string('H', data, Replay._header_struct1.size)

        self.random_seed, seat_mask = Replay._header_struct2.unpack_from(data, offset)
        offset += Replay._header_struct2.size

        self.player_seats = _unpack_bitmask(seat_mask, 16)

        self._data = data
        self._base_offset = offset

    def raw_messages(self):
        offset = self._base_offset
        while offset < len(self._data):
            timestamp, msg_type, message, seat = Replay._body_struct.unpack_from(self._data, offset)
            offset += Replay._body_struct.size
            params, offset = _read_length_prefixed_field('I', self._data, offset)
            yield timestamp, msg_type, message, seat, params

    def messages(self):
        player_seat_map = {}
        for timestamp, msg_type, message, seat, params in self.raw_messages():
            player = player_seat_map.get(seat, seat)
            try:
                msg = make_replay_message(timestamp, msg_type, message, player, params)
            except:
                print("\nERROR parsing replay message:")
                print("Timestamp: %s" % timestamp)
                print("Message type: %s" % MessageType.reverse_mapping.get(msg_type, "unknown (number %d)" % msg_type))
                print("Message content: %s" % MessageContentType.reverse_mapping.get(message, "unknown (number %d)" % message))
                print("Player: %s" % player)
                print("Parameters: %s" % params)
                raise

            if isinstance(msg, NewClientMessage):
                player_seat_map[seat] = msg.player
            elif isinstance(msg, DisconnectedMessage):
                del player_seat_map[seat]

            if isinstance(msg, list):
                for m in msg:
                    yield m
            else:
                yield msg


if __name__ == "__main__":
    parser = OptionParser(usage="usage: %prog REPLAY")
    try:
        options, (replay_path,) = parser.parse_args()
    except ValueError:
        parser.error("Path to replay is required.")

    with open(replay_path, 'rb') as replay_file:
        for message in Replay(replay_file.read()).messages():
            if not isinstance(message, NoOpMessage):
                print("[%s]\t%s" % (format_timestamp(message.timestamp), message))
