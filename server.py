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
        self.__rank = int(rank)
        self.__suit = int(suit)

    def get_rank(self):
        # Ace is 11, Face cards are 10
        if self.__rank >= 11: return 10
        return self.__rank

    def get_suit(self):
        return self.__suit

    def __str__(self):
        r_str = {1: 'Ace', 11: 'Jak', 12: 'Queen', 13: 'King'}.get(self.__rank, str(self.__rank))
        return f"{r_str} of {SUITS[self.__suit]}"


def calculate_hand_value(cards):
    """
    Calculate the total value of a hand based on card ranks.
    """
    total = 0
    aces = 0
    for card in cards:
        rank = card.get_rank()
        if rank == 1:
            aces += 1
            total += 11
        else:
            total += rank
    # Adjust for aces if bust
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

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
    rank = card.get_rank() if card else 0
    suit = card.get_suit() if card else 0
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
    team_name = "Unknown"
    round_num = 0

    def game_log(message):
        if round_num:
            print(f"[Team: {team_name}, Round: {round_num}] {message}")
        else:
            print(f"[Client {addr}] {message}")

    game_log(f"Client connected from {addr}")

    conn.settimeout(120.0)
    try:
        try:
            # Receive Request (Header + Name)
            # Cookie(4), Type(1), Rounds(1), Name(32) = 38 bytes
            req_data = conn.recv(38)
        except socket.timeout:
            game_log("Timeout waiting for handshake data.")
            return
        if not req_data or len(req_data) < 38:
            game_log("Error During Handshake - Corrupted data")
            return

        cookie, mtype, num_rounds, team_name_b = struct.unpack("!IBB32s", req_data)
        if cookie != MAGIC_COOKIE or mtype != REQUEST_TYPE:
            game_log("Error During Handshake - Invalid cookie or type")
            return

        team_name = team_name_b.decode('utf-8').strip('\x00')
        game_log(f"Game starting with {team_name} for {num_rounds} rounds.")

        total_wins = 0
        # Game Loop
        for round_num in range(1, num_rounds + 1):
            print(f"             --- Start Round {round_num} ---")
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

            game_log(f"Dealt: {card1}, {card2}")
            game_log(f"Dealer dealt: {d_card1} [Hidden]\n")

            # Send initial cards to client
            try:
                # Send Player's cards
                conn.sendall(pack_server_payload(ROUND_NOT_OVER, card1))
                conn.sendall(pack_server_payload(ROUND_NOT_OVER, card2))
                # Send Dealer's FIRST card only
                conn.sendall(pack_server_payload(ROUND_NOT_OVER, d_card1))
            except socket.error as e:
                game_log(f"Error sending initial cards: {e}")
                return

            # --- Player's Turn ---
            player_busted = False
            while True:
                try:
                    # Wait for player decision
                    data = conn.recv(10)
                except socket.timeout:
                    game_log(f"Timeout waiting for decision.")
                    return

                if not data:
                    game_log(f"Connection lost.")
                    return

                # Parse decision
                cookie, _, decision_bytes = unpack_client_payload(data)
                # Validate cookie, if invalid, ignore and continue
                if cookie != MAGIC_COOKIE: continue

                decision = decision_bytes.decode('utf-8')
                game_log(f"Chose to: {decision}")

                if decision == "Hittt":
                    new_card = deck.pop()
                    player_hand.append(new_card)
                    game_log(f"Drew: {new_card}\n")

                    # Check value immediately
                    p_val = calculate_hand_value(player_hand)

                    if p_val > 21:
                        game_log(f"BUSTED with value {p_val}!")
                        # BUST! Send the card AND the Loss result together
                        conn.sendall(pack_server_payload(LOSS, new_card))
                        player_busted = True
                        break  # End player turn
                    else:
                        # Safe hit
                        conn.sendall(pack_server_payload(ROUND_NOT_OVER, new_card))

                elif decision == "Stand":
                    break

            result = LOSS  # Default result if player busted
            # --- Dealer's Turn (only if player didn't bust) ---
            if not player_busted:
                # Reveal hidden card (Send it to client)
                # Note: Protocol doesn't have "Reveal" type, so we send it as a card update
                game_log(f"Dealer reveals hidden card: {d_card2}")
                conn.sendall(pack_server_payload(ROUND_NOT_OVER, d_card2))

                # Dealer logic: Hit until >= 17
                while calculate_hand_value(dealer_hand) < 17:
                    new_card = deck.pop()
                    dealer_hand.append(new_card)
                    game_log(f"Dealer draws: {new_card}\n")
                    conn.sendall(pack_server_payload(ROUND_NOT_OVER, new_card))

                # Calculate Winner
                p_sum = calculate_hand_value(player_hand)
                d_sum = calculate_hand_value(dealer_hand)
                game_log(f"Final value: {p_sum}  |  Dealer final value: {d_sum}")

                if d_sum > 21:  # Dealer bust
                    result = WIN
                elif p_sum > d_sum:
                    result = WIN
                elif p_sum == d_sum:
                    result = TIE

                # Send Final Result (No card attached)
                conn.sendall(pack_server_payload(result, None))
                if result == WIN:
                    game_log(f"Player WINS the round!")
                    total_wins += 1
        game_log(f"Game over. Total Wins: {total_wins} out of {num_rounds}\n")

    except Exception as e:
        game_log(f"Error handling client {addr}: {e}")
    finally:
        conn.close()
        game_log(f"Client {addr} closed.")


def udp_broadcast(tcp_port):
    """ Broadcasts offer every 1 second """
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    # Pad name to 32 bytes
    server_name = "BlackjackServer".encode('utf-8')
    server_name += b'\x00' * (32 - len(server_name))

    # Offer: Cookie(4), Type(1), Port(2), Name(32)
    packet = struct.pack("!IBH32s", MAGIC_COOKIE, OFFER_TYPE, tcp_port, server_name)
    print(f"Starting UDP broadcast on port {UDP_PORT} for TCP port {tcp_port}")

    while True:
        try:
            udp_sock.sendto(packet, ('<broadcast>', UDP_PORT))
            time.sleep(1)
        except Exception as e:
            print(f"Error in UDP broadcast: {e}")
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

    print(f"Server started, listening on IP address {ip_address}, Port {tcp_port}")

    # Start UDP Broadcast thread
    t = threading.Thread(target=udp_broadcast, args=(tcp_port,), daemon=True)
    t.start()

    try:
        while True:
            conn, addr = tcp_sock.accept()
            t_client = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t_client.start()
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        tcp_sock.close()

if __name__ == "__main__":
    start_server()
