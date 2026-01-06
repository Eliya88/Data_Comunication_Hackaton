import socket
import struct
import threading
import time
import random
from constants import MAGIC_COOKIE, PAYLOAD_TYPE, UDP_PORT

# --- Constants ---
OFFER_TYPE = 0x2
REQUEST_TYPE = 0x3
SERVER_NAME_LEN = 32

# Result codes
ROUND_NOT_OVER = 0x0
TIE = 0x1
LOSS = 0x2
WIN = 0x3

SUITS = ["Heart", "Diamond", "Clubs", "Spades"]


class Card:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def value(self):
        # Ace is 11, Face cards are 10
        if self.rank == 1: return 11
        if self.rank >= 11: return 10
        return self.rank

    def __str__(self):
        r_str = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(self.rank, str(self.rank))
        return f"{r_str}{SUITS[self.suit]}"


def create_deck():
    # Suit: 0-3, Rank: 1-13
    deck = [Card(r, s) for s in range(4) for r in range(1, 14)]
    random.shuffle(deck)
    return deck


def pack_server_payload(result, card=None):
    """
    Server -> Client Packet Structure (9 bytes):
    Magic Cookie (4), Type (1), Result (1), Rank (2), Suit (1)
    """
    rank = card.rank if card else 0
    suit = card.suit if card else 0
    # ! = Network (Big Endian), I = Int(4), B = Char(1), B = Char(1), H = Short(2), B = Char(1)
    return struct.pack("!IBBHB", MAGIC_COOKIE, PAYLOAD_TYPE, result, rank, suit)


def unpack_client_payload(data):
    """
    Client -> Server Packet Structure (10 bytes):
    Magic Cookie (4), Type (1), Decision (5 bytes string)
    """
    try:
        cookie, mtype, decision = struct.unpack("!IB5s", data)
        return cookie, mtype, decision
    except struct.error:
        return None, None, None


def handle_client(conn, addr):
    print(f"Client connected from {addr}")
    conn.settimeout(60.0)  # Timeout generous for gameplay

    try:
        # 1. Receive Request (Header + Name)
        # Request: Cookie(4), Type(1), Rounds(1), Name(32) = 38 bytes
        req_data = conn.recv(38)
        if len(req_data) < 38:
            return

        cookie, mtype, num_rounds, team_name = struct.unpack("!IBB32s", req_data)
        if cookie != MAGIC_COOKIE or mtype != REQUEST_TYPE:
            print("Invalid handshake")
            return

        team_name = team_name.decode('utf-8').strip('\x00')
        print(f"Game starting with {team_name} for {num_rounds} rounds.")

        # --- Game Loop ---
        for round_num in range(1, num_rounds + 1):
            deck = create_deck()
            player_hand = []
            dealer_hand = []

            # Deal initial cards
            # Player gets 2 cards
            card1 = deck.pop()
            card2 = deck.pop()
            player_hand.extend([card1, card2])

            # Dealer gets 2 cards (one hidden)
            d_card1 = deck.pop()  # Visible
            d_card2 = deck.pop()  # Hidden
            dealer_hand.extend([d_card1, d_card2])

            # Send Player's cards
            conn.sendall(pack_server_payload(ROUND_NOT_OVER, card1))
            conn.sendall(pack_server_payload(ROUND_NOT_OVER, card2))

            # Send Dealer's FIRST card only
            conn.sendall(pack_server_payload(ROUND_NOT_OVER, d_card1))

            # --- Player's Turn ---
            player_busted = False
            while True:
                # Wait for decision (10 bytes)
                data = conn.recv(10)
                if not data: break

                _, _, decision_bytes = unpack_client_payload(data)
                decision = decision_bytes.decode('utf-8')

                if decision == "Hittt":
                    new_card = deck.pop()
                    player_hand.append(new_card)

                    # Check value immediately
                    p_val = sum(c.value() for c in player_hand)

                    if p_val > 21:
                        # BUST! Send the card AND the Loss result together
                        conn.sendall(pack_server_payload(LOSS, new_card))
                        player_busted = True
                        break  # End player turn
                    else:
                        # Safe hit
                        conn.sendall(pack_server_payload(ROUND_NOT_OVER, new_card))

                elif decision == "Stand":
                    break

            # --- Dealer's Turn (only if player didn't bust) ---
            if not player_busted:
                # Reveal hidden card (Send it to client)
                # Note: Protocol doesn't have "Reveal" type, so we send it as a card update
                conn.sendall(pack_server_payload(ROUND_NOT_OVER, d_card2))

                # Dealer logic: Hit until >= 17
                while sum(c.value() for c in dealer_hand) < 17:
                    new_card = deck.pop()
                    dealer_hand.append(new_card)
                    conn.sendall(pack_server_payload(ROUND_NOT_OVER, new_card))

                # Calculate Winner
                p_sum = sum(c.value() for c in player_hand)
                d_sum = sum(c.value() for c in dealer_hand)

                result = 0
                if d_sum > 21:  # Dealer bust
                    result = WIN
                elif p_sum > d_sum:
                    result = WIN
                elif p_sum == d_sum:
                    result = TIE
                else:
                    result = LOSS

                # Send Final Result (No card attached)
                conn.sendall(pack_server_payload(result, None))

    except Exception as e:
        print(f"Error handling client {addr}: {e}")
    finally:
        conn.close()


def udp_broadcast(tcp_port):
    """ Broadcasts offer every 1 second """
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    # Pad name to 32 bytes
    server_name = "BlackjackServer".encode('utf-8')
    server_name += b'\x00' * (32 - len(server_name))

    # Offer: Cookie(4), Type(1), Port(2), Name(32)
    packet = struct.pack("!IBH32s", MAGIC_COOKIE, OFFER_TYPE, tcp_port, server_name)

    while True:
        udp_sock.sendto(packet, ('<broadcast>', UDP_PORT))
        time.sleep(1)


def start_server():
    # Find local IP
    try:
        ip_address = socket.gethostbyname(socket.gethostname())
    except:
        ip_address = '127.0.0.1'

    # Setup TCP
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.bind(("", 0))  # Ephemeral port
    tcp_sock.listen(5)
    tcp_port = tcp_sock.getsockname()[1]

    print(f"Server started, listening on IP address {ip_address}")

    # Start UDP Broadcast thread
    t = threading.Thread(target=udp_broadcast, args=(tcp_port,), daemon=True)
    t.start()

    while True:
        conn, addr = tcp_sock.accept()
        t_client = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t_client.start()


if __name__ == "__main__":
    start_server()