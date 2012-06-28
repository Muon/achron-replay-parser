#!/usr/bin/env python

import struct
from collections import defaultdict
from optparse import OptionParser


def enum(*sequential, **named):
    """See http://stackoverflow.com/questions/36932/whats-the-best-way-to-implement-an-enum-in-python"""
    enums = dict(zip(sequential, range(len(sequential))), **named)
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


def _format_ticks(ticks):
    minutes, ticks = divmod(ticks, GAME_TICKS_PER_SECOND * 60)
    seconds, ticks = divmod(ticks, GAME_TICKS_PER_SECOND)
    return "%dm %ds %dt" % (minutes, seconds, ticks)

MessageType = enum(
    "NO_MESSAGE",
    "MESSAGE",
    "NEW_CLIENT",
    "NEW_BANNED_CLIENT",
    "DISCONNECTED",
    "ERROR"
)

MessageContentType = enum(
    CHRONAL_COMMANDS=16,
    SEND_TEXT=32,
    BROADCAST_TEXT=33,
    UNPAUSE_ENGINE=37,
    PAUSE_ENGINE=38,
    SAVE_GAME=40,
    SURRENDER=41
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
    "REVOKE_VISIBILITY_FROM_PLAY",
    "FAST_TIME",
    "SLOW_TIME",
    "STOP_TIME",
    "NORMAL_TIME"
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
        return "Player %d (%s)" % (self.seat, self.name)


class BaseReplayMessage(object):
    """Parent class of all replay messages."""
    def __init__(self, timestamp, message, player, data):
        self.timestamp = timestamp
        player._update_timestamp(timestamp)
        self.player = player


class NetworkMessage(BaseReplayMessage):
    """Parent class of all network-related replay messages."""
    pass


class NoOpMessage(NetworkMessage):
    def __str__(self):
        return "Nothing happens"


class NewClientMessage(NetworkMessage):
    def __init__(self, timestamp, message, player, data):
        self.player = player = Player(player, data.decode('ascii'))
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


# Commands

class BaseCommand(GameMessage):
    _data_struct = struct.Struct("<")


class MoveTimePosition(BaseCommand):
    def __init__(self, timestamp, message, player, data):
        super(MoveTimePosition, self).__init__(timestamp, message, player, data)
        self.target_time, = struct.unpack("<I", data)
        player.time_position = self.target_time

    def __str__(self):
        return "%s jumps to to time %s" % (self.player,
                _format_ticks(self.target_time))

objectives = {0: ['Idle/Defend', '', 'Landing', 'Progeneration', '---', 'Defend', 'Moving', 'Attacking...', 'Importing Reserves', 'Idle'], 1: ['Move', 'display waypoint', 'New (Down)', 'Attack Unit', 'Processing', 'Build MFB', 'Time Warping', 'Build Tornade', 'Relocate'], 2: ['Attack', 'New (Up)', 'Process Resource', 'Move', 'Process Resources', 'Exploding', 'Build Frigate', 'Create Marines', 'Build Mech', 'Change Controller'], 3: ['Patrol', 'New (Down Left)', 'Make Octo', 'Build MFB', 'Create SOPs', 'Build ATHC', 'Create Unit'], 4: ['Attack Unit', 'New (Down Right)', 'Make Sepi', 'Turn AutoCommand ON', 'Turn Auto Hierarchy ON', 'Build Blackbird', 'Build Lancer', 'Release Unit'], 5: ['Moving', 'New (Up Left)', 'Make Pharo', 'Turn Smart Idle ON', 'Build Heavy Cruiser', 'Out', 'Build Tornade', 'Take Unit'], 6: ['Attacking', 'New (Up Right)', 'Moving', 'Turn AutoCommand OFF', 'Turn Auto Hierarchy OFF', 'Build MAR Tank', 'Build Tank', 'Teleport Unit'], 7: ['Patrolling', 'Turn Smart Idle OFF', 'Build Heavy Cruiser', 'Build Tank', 'Kill Unit'], 8: ['Change Commander', 'Select Unit', 'Relocate', 'Attack', 'Build Blackbird', 'Attack Unit', 'displaying waypoint'], 9: ['Remove from Hierarchy', 'Remove from Heirarchy', 'Relocate', 'Move', 'Clear Commander', 'Rotate Unit'], 10: ['Priority', 'Lead group', 'Moving', 'Teleport Self To', 'Move'], 11: ['Build', 'Nanite Infect', 'Place buildings', 'Activating', 'Merge', 'Stop and re-enable', 'Load Unit', 'Build Foundation', 'Chrono-Freeze', 'Stopping', 'Defend/Repel', 'Build Resource Processor', 'Build Comm Hub', 'Drop Nuke Now ', 'Resource Processor', 'Comm Jam', 'Morph: Reaph', 'Morph: Arcticus'], 12: ['Clear Nanite', 'Build Foundation', 'Upgrade Tank', 'Activate', 'Merge', 'Release Cargo', 'Upgrade', 'Temporal Soliton Shield', 'Stop', 'Nuke a Location', 'Moving to Morph '], 13: ['Ride in a Tank', 'Cancel Progen for All', 'Cancel Build', 'Merge', 'LCrystal -&gt; QPlasma', 'Merging', 'Clear Nanite', 'Morph to Pharo', 'displaying waypoint', 'QPlasma -&gt; LCrystal'], 14: ['Cancel Build', 'Fix Troops', 'Cancel Factory/Progeneration', 'Cancel Make Buildings', 'Clear Nanite', 'Fix Unit', 'Recharging', 'Cancel Piloting', 'Reload Nuke', 'Cancel Progeneration'], 15: ['Cancel Build', 'Recover Status', 'Recover', 'Break TSS', 'Deploying Units', 'Deploying Troops', 'Deploy Unit'], 16: ['Stop', 'Chronobomb', 'Deploying Units', 'Deploying Troops', 'Temporal Soliton Shield', 'PreDeploy'], 17: ['Release Troop', 'ChronoBomb', 'Release Unit', 'Break TSS', 'Cloaking On', 'Morph: Dome'], 18: ['', 'Congregate units at', 'Plasma Bomb', 'Congregate Units At', 'Congregate Troops At', 'Morph: Dome', 'Morph: Mound'], 19: ['', 'Clear Congregation Point', 'Upgrade Tank', 'Upgrade Skip-Teleport', 'Upgrading', 'Chronobomb', 'Upgrade Beam', 'Repel', 'Upgrade'], 20: ['Rally on unit', 'Skip Torpedo', 'Nanite Infect', 'Plasma Bomb', 'Fire Charge Beam', 'Uncloak', 'Repel', 'Chrono-Freeze ', 'Equip Nuke', 'Auto Slingshot', 'Defend/Repel', 'Launch Skip Torpedo', 'Comm Jam'], 21: ['Teleport Self To', 'Relink (to Arcticus)', 'ChronoBomb', '', 'Rally on unit', 'Cancel Defend/Repel'], 22: ['Resource Processor', 'Slingshot', 'Skip Torpedo', 'Attack Dispatch', 'Plasma Bomb', 'Equip Nuke'], 23: ['Importer', 'Teleporter', 'Move Dispatch', 'ChronoBomb', '', 'displaying waypoint', 'Auto Slingshot Enabled'], 24: ['Factory', 'Defense Turret', 'Stop Dispatch', 'Upgrade Adv Structures', 'Make Vehicles', 'Upgrade Machinery', 'Upgrade Autodefence'], 25: ['Armory', 'Macrofab', 'Chronoport Dispatch', '', 'Make Vehicles'], 26: ['Comm Center', 'Defense Turret', 'Make Resource Processor', 'Upgrade Loligo Class', 'Upgrade Ground Units', 'Research Halcyon Class'], 27: ['Slingshot', 'Create Depot', 'Make Mound', ''], 28: ['Chronoporter', 'Make Reaph', 'Upgrade Specials'], 29: ['Teleporter', 'Create Annex', 'Make Arcticus', ''], 30: ['Chronoporter', 'Make Spyre', 'Upgrade Chronoporting', 'Zayin Pulser', 'Upgrade Gate Tech'], 31: ['Carrier', 'Make Dome', '', 'Teth Pulser', 'Garguntuan', 'Spyre'], 32: ['Carrier', 'Make Dome', 'Upgrade Weapons', 'Shin Pulser', 'Upgrade Aerospace', '', 'Upgrade Weaponry', 'Spyre'], 33: ['Awaiting Air-Lift', 'Make Spyre', '', 'Zayin Tercher'], 34: ['Carry/Commander', 'Select Unit', 'Create SlipGate', 'Chronoport Dispatch', 'Teth Tercher'], 35: ['Carrier', 'Create Bastion', 'Shin Tercher'], 36: ['Importer', 'Create Incepter', 'Upgrade Chronoporting', 'Zayin Halcyon', 'Upgrade Gate Tech', 'Octo RP Dispatch'], 37: ['Armory', 'Create Incepter', 'Upgrade Chronoporting', 'Teth Halcyon', 'Factory/Progeneration'], 38: ['Produce Octopod', 'Upgrade Weapons', 'Shin Halcyon', 'Upgrade Aerospace', 'Upgrade Weaponry', 'Produce Octo'], 39: ['Produce Sepipod', 'Create Incepter', 'Upgrade Weapons', '', 'Upgrade Aerospace', 'Upgrade Weaponry', 'Pilot Vehicle', 'Produce Sepi'], 40: ['Produce Pharopod', 'Upgrade Adv Structures', 'Shin Pulser', 'Split Down', 'Upgrade Machinery', 'Upgrade Autodefense', 'Pilot Pulser', 'Produce Pharo'], 41: ['Produce Octoligo', 'Upgrade Specials', 'Teth Tercher', 'Equip Nuke', 'Pilot Tercher', 'Produce Octopod'], 42: ['Produce Sepiligo', 'Preparing Halcyon', 'Upgrade Loligo Class', 'Shin Tercher', 'Upgrade Ground Units', 'Research Halcyon Class', 'Pilot Halcyon', 'Produce Sepipod'], 43: ['Produce Pharoligo', 'Zayin Halcyon', 'Create Marines', 'Create Zayin Vir', 'Pilot Halcyon', 'Produce Pharopod'], 44: ['Octopod', 'Repairing in Depot', 'Teth Halcyon', 'Create SOPs', 'Create Teth Vir', 'Octo'], 45: ['Chronoport', '', 'Sepipod', 'Shin Halcyon', 'Create Shin Vir', 'Sepi'], 46: ['Chronoport', 'Pharopod', 'Shin Halcyon', 'Chronoport ', 'Create Zayin Vir', 'Pharo'], 47: ['Teleport', 'Octoligo', 'Teleport Self To', 'Create Teth Vir', 'Octopod'], 48: ['Chronoport', 'Sepiligo', 'Create Shin Vir', 'Sepipod'], 49: ['MoveAway', 'Move Away', 'Pharoligo', 'Pharopod', 'Pharpod'], 50: ['Teleport', '', 'Octoligo', 'Constructing...', 'Morphing...', 'Human'], 51: ['Sepiligo', '', 'Grekim'], 52: ['Pharoligo', 'Imprison', '', 'Vecgir', 'Upgrade Power', 'Octo Resource Processor'], 53: ['Sepiligo', '', 'Random', 'Upgrade Power'], 54: ['Attacking Unit', 'Pharoligo', 'Upgrade Power'], 55: ['Sepipod'], 56: ['Pharopod'], 57: ['Create Slipgate', ''], 58: ['Create Bastion', ''], 59: ['Create ACC']}


def _lower_bitmask(n):
    bitmask = 0
    for i in range(n):
        bitmask |= 1 << i
    return bitmask


class AssignUnitObjective(BaseCommand):
    _data_struct = struct.Struct("<HBI")

    def __init__(self, timestamp, message, player, data):
        super(AssignUnitObjective, self).__init__(timestamp, message, player, data)
        self.unit, objective, params = AssignUnitObjective._data_struct.unpack_from(data)
        self.objective = objective & _lower_bitmask(6)
        self.queued = bool(objective & (1 << 7))

    def __str__(self):
        method = "assigns"
        if self.queued:
            method = "queued"

        return "%s %s unit %d objective %d (one of %s)" % (self.player, method,
            self.unit, self.objective, ', '.join(objectives[self.objective]))


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
            self.unit, self.objective, ', '.join(objectives[self.objective]))


class MarkUnit(BaseCommand):
    _data_struct = struct.Struct("<H")

    def __init__(self, timestamp, message, player, data):
        super(MarkUnit, self).__init__(timestamp, message, player, data)
        self.unit, = MarkUnit._data_struct.unpack("<H", data)

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
            self.unit, _format_ticks(self.start_time),
            _format_ticks(self.end_time))


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


def ReplayMessage(timestamp, message_type, message, player, data):
    return defaultdict(lambda: BaseReplayMessage, {
        MessageType.NO_MESSAGE: NoOpMessage,
        MessageType.MESSAGE: Message,
        MessageType.NEW_CLIENT: NewClientMessage,
        MessageType.NEW_BANNED_CLIENT: NewBannedClientMessage,
        MessageType.DISCONNECTED: DisconnectedMessage,
        MessageType.ERROR: ErrorMessage
    })[message_type](timestamp, message, player, data)


def Message(timestamp, message, player, data):
    return defaultdict(lambda: GameMessage, {
        MessageContentType.CHRONAL_COMMANDS: Command,
        MessageContentType.SEND_TEXT: PrivateChatMessage,
        MessageContentType.BROADCAST_TEXT: PublicChatMessage,
        MessageContentType.UNPAUSE_ENGINE: UnpauseEngine,
        MessageContentType.PAUSE_ENGINE: PauseEngine,
        MessageContentType.SAVE_GAME: SaveGame,
        MessageContentType.SURRENDER: PlayerSurrender
    })[message](timestamp, message, player, data)


_command_struct = struct.Struct("<B")


def Command(timestamp, message, player, data):
    command_count, = _command_struct.unpack_from(data)
    data = data[_command_struct.size:]
    results = []

    for i in range(command_count):
        command_number, = _command_struct.unpack_from(data)
        data = data[_command_struct.size:]

        command = defaultdict(lambda: BaseCommand, {
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
            CommandType.GIVE_VISIBILITY_TO_PLAYER: ShareVision,
            CommandType.REVOKE_VISIBILITY_FROM_PLAY: RevokeVision,
            CommandType.FAST_TIME: SwitchFastForward,
            CommandType.SLOW_TIME: SwitchSlowMotion,
            CommandType.STOP_TIME: SwitchPause,
            CommandType.NORMAL_TIME: SwitchNormalTime,
        })[command_number]

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
        while True:
            timestamp, msg_type, message, seat = Replay._body_struct.unpack_from(self._data, offset)
            offset += Replay._body_struct.size
            params, offset = _read_length_prefixed_field('I', self._data, offset)
            yield timestamp, msg_type, message, seat, params

            if offset >= len(self._data):
                return

    def messages(self):
        player_seat_map = {}
        for timestamp, msg_type, message, seat, params in self.raw_messages():
            player = player_seat_map.get(seat, seat)
            msg = ReplayMessage(timestamp, msg_type, message, player, params)

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
            print(message)
