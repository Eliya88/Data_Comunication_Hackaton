import socket
import struct
from constants import MAGIC_COOKIE, PAYLOAD_TYPE, UDP_PORT


def pack_client_decision(decision):
    """
    Client -> Server (10 bytes): Cookie(4), Type(1), Decision(5)
    """
    # Decision must be 5 bytes: "Hittt" or "Stand"
    return struct.pack("!IB5s", MAGIC_COOKIE, PAYLOAD_TYPE, decision)


def unpack_server_payload(data):
    """
    Server -> Client (9 bytes): Cookie(4), Type(1), Result(1), Rank(2), Suit(1)
    """
    if not data or len(data) < 9: return None
    try:
        cookie, mtype, result, rank, suit = struct.unpack("!IBBHB", data)
        return result, rank, suit
    except struct.error:
        return None

def get_suit_char(suit_int):
    return ["Heart", "Diamond", "Clubs", "Spades"][suit_int]

def get_rank_str(rank_int):
    if rank_int == 1: return "Ace"
    if rank_int == 11: return "Jack"
    if rank_int == 12: return "Queen"
    if rank_int == 13: return "King"
    return str(rank_int)

def calculate_hand(cards):
    """
    Calculate the total value of a hand based on card ranks.
    :param cards: list of card ranks (integers)
    :return: total value of the hand (integer)
    """
    total = 0
    aces = 0
    for card in cards:
        if card[0] == 1:
            aces += 1
            total += 11  # Ace
        elif card[0] >= 11:
            total += 10  # J, Q, K
        else:
            total += card[0]  # 2-10

    while total > 21 and aces > 0:
        total -= 10
        aces -= 1

    return (total, aces)

def print_hand(cards, owner):
    return f"\n{owner} Hand: " + ", ".join(f"{get_rank_str(card[0])} of {get_suit_char(card[1])}" for card in cards)


def client_main():
    team_name = "Team Tim"

    # Enable reuse port for testing multiple clients on same machine
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        # Some OS (like Windows) don't support SO_REUSEPORT, use SO_REUSEADDR
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    udp_sock.bind(("", UDP_PORT))

    print("Client started...")

    while True:
        try:
            print("Client started, listening for offer requests...")
            # Wait for Offer
            data, addr = udp_sock.recvfrom(1024)
            # Offer: Cookie(4), Type(1), Port(2), Name(32) = 39 bytes
            if len(data) < 39: continue

            cookie, mtype, server_port, server_name = struct.unpack("!IBH32s", data[:39])
            if cookie != MAGIC_COOKIE or mtype != 0x2:
                continue

            s_name = server_name.decode('utf-8').strip('\x00')
            print(f"Received offer from s_name at {addr[0]}, attempting to connect...")

            # Connect TCP
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.connect((addr[0], server_port))

            # 3. Send Request
            # Ask user for rounds
            rounds = 0
            while rounds < 1:
                try:
                    rounds = int(input("How many rounds you want to play? "))
                except ValueError:
                    print("Invalid input, please enter a number.")

            # Request: Cookie(4), Type(1), Rounds(1), Name(32)
            name_bytes = team_name.encode('utf-8') + b'\x00' * (32 - len(team_name))
            req_pkt = struct.pack("!IBB32s", MAGIC_COOKIE, 0x3, rounds, name_bytes)
            tcp_sock.sendall(req_pkt)

            wins=0
            ties=0

            # --- Game Loop ---
            for r in range(rounds):
                print(f"\n--- Round {r + 1} ---")

                player_cards = []
                dealer_cards = []

                # Receive initial cards (Player 1, Player 2, Dealer 1)
                # We expect 3 packets of 9 bytes each
                for _ in range(2):
                    data = tcp_sock.recv(9)
                    package = unpack_server_payload(data)
                    if not package:
                        raise ConnectionError("Failed to receive initial player cards.")
                    res, rank, suit = package
                    print(f"Your card: {get_rank_str(rank)} of {get_suit_char(suit)}")
                    player_cards.append((rank, suit))

                hand, ace = calculate_hand(player_cards)
                if ace == 0:
                    print(f"Your hand total: {hand}\n")
                else:
                    print(f"Your hand total is: {hand} or {hand - 10}\n")

                data = tcp_sock.recv(9)
                package = unpack_server_payload(data)
                if not package:
                    raise ConnectionError("Failed to receive initial dealer card.")
                res, rank, suit = package
                print(f"Dealer first card: {get_rank_str(rank)} of {get_suit_char(suit)}")
                print(f"Dealer second card is hidden.\n{'-'*30}\n")
                dealer_cards.append((rank, suit))

                # Player turn
                game_over = False
                while not game_over:
                    # Check if server already sent "Loss" (e.g. from previous hit busting)
                    if res != 0:
                        game_over = True
                        break

                    hand, _ = calculate_hand(player_cards)
                    if hand == 21:
                        if len(player_cards) == 2:
                            print("Blackjack! You have 21.")
                        tcp_sock.sendall(pack_client_decision(b"Stand"))
                        break

                    choice = ''
                    while choice not in ['s', 'h']:
                        choice = input("Type 'h' to Hit, 's' to Stand: ").lower()

                    if choice == 'h':
                        tcp_sock.sendall(pack_client_decision(b"Hittt"))

                        # Get response (Card or Result)
                        data = tcp_sock.recv(9)
                        package = unpack_server_payload(data)
                        if not package:
                            raise ConnectionError("Failed to receive card after Hit.")
                        res, rank, suit = package

                        if rank != 0:
                            player_cards.append((rank, suit))
                            print(f"You drew: {get_rank_str(rank)} of {get_suit_char(suit)}")
                            hand, ace = calculate_hand(player_cards)
                            if ace == 0:
                                print(f"Your hand total: {hand}\n")
                            else:
                                print(f"Your hand total is: {hand} or {hand - 10}\n")
                            if hand > 21:
                                game_over = True


                    elif choice == 's':
                        tcp_sock.sendall(pack_client_decision(b"Stand"))
                        break  # Exit user input loop, wait for dealer


                # Wait for Dealer sequence and final result
                while True:
                    if not game_over:
                        data = tcp_sock.recv(9)
                        package = unpack_server_payload(data)
                        if not package:
                            raise ConnectionError("Failed to receive dealer card/result.")
                        res, rank, suit = package

                    if res != 0:  # Game ended (Win/Loss/Tie)
                        if res == 2:
                            hand, ace = calculate_hand(player_cards)
                            if hand > 21:
                                print("You Busted!")
                            else:
                                print(print_hand(dealer_cards, "Dealer"))
                                print(f"Dealer have total value of {calculate_hand(dealer_cards)[0]}")
                                print(f"Your hand total: {hand}\n")
                                print("You Lost!")
                        elif res == 3:
                            wins+=1
                            print(print_hand(dealer_cards, "Dealer"))
                            print(f"Dealer have total value of {calculate_hand(dealer_cards)[0]}\n")
                            print("You Won!")

                        elif res == 1:
                            ties+=1
                            print(print_hand(dealer_cards, "Dealer"))
                            print(f"Dealer have total value of {calculate_hand(dealer_cards)[0]}\n")
                            print("Tie!")

                        print("Round over.\n")
                        break
                    else:
                        # Dealer drew a card
                        if len(dealer_cards) == 1:
                            print(f"Dealer reveals hidden card: {get_rank_str(rank)} of {get_suit_char(suit)}")
                        else:
                            print(f"Dealer draw: {get_rank_str(rank)} of {get_suit_char(suit)}")

                        dealer_cards.append((rank, suit))

            if wins == rounds:
                print(f"Congratulations! You won all {rounds} rounds!")
            elif wins == 0 and ties == 0:
                print(f"Unfortunately, you lost all {rounds} rounds. Never play again!")
            else:
                print(f"Finished playing {rounds} rounds, win rate: {(wins/rounds)*100}%")

            print("All rounds finished. Disconnecting.\n")
            print("You Won ")

            tcp_sock.close()
            # Loop back to UDP listening


        except KeyboardInterrupt:
            print("Client shutting down.")
            break
        except Exception as e:
            print(f"An error occurred: {e}")
            if 'tcp_sock' in locals():
                tcp_sock.close()

if __name__ == "__main__":
    client_main()
