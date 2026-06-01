new Vue({
    el: '#app',
    delimiters: ['[[', ']]'], // Change delimiters to avoid conflict with Tornado
    data: {
        socket: null,
        players: [], // Start with an empty array
        playerColors: [
            '#ffffe0', '#e3dac9', '#318ce7', '#0b486b', '#272941', '#1cceb7', '#008080', '#1b4d3e',
            '#2c9c38', '#f0a830', '#ffa4e9', '#e95081', '#7b1e7a', '#841b2d'
        ],
        playerTextColor: [
            'black', 'black', 'white', 'white', 'white', 'black', 'white', 'white',
            'black', 'black', 'black', 'white', 'white', 'white'
        ],
        messages: [],
        autoScrollEnabled: true,
        userHasScrolled: false
    },
    methods: {
        formatTimestamp(timestamp) {
            if (!timestamp) return '';
            const date = new Date(timestamp);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        },
        addMessage(message) {
            this.messages.push(message);
            this.$nextTick(() => {
                if (this.autoScrollEnabled) {
                    this.scrollToBottom();
                }
            });
        },
        isUserAtBottom() {
            const container = this.$refs.messageContainer;
            if (!container) return true;
            // Allow a small threshold (e.g. 40px) for 'near the bottom'
            return container.scrollTop + container.clientHeight >= container.scrollHeight - 40;
        },
        scrollToBottom() {
            const container = this.$refs.messageContainer;
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        },
        getRoleImage(role) {
            if (role === 'voyante') return 'img/seer.png';
            if (role === 'villageois') return 'img/villager.png';
            if (role === 'loup-garou') return 'img/werewolf.png';
            return 'img/placeholder.png';
        },
        markPlayerAsEliminated(victimName) {
            const player = this.players.find(p => p.name === victimName);
            if (player) {
                player.eliminated = true;
            }
        },
        initializeSocket() {
            // Connect to WebSocket server
            this.socket = io();
            // Listen for new log entries
            this.socket.on('new_log_entry', (message) => {
                // Special handling for ROLE_ASSIGNMENT
                if (message.type === 'ROLE_ASSIGNMENT') {
                    const playerIndex = this.players.length;
                    this.players.push({
                        name: message.target_name,
                        color: this.playerColors[playerIndex % this.playerColors.length],
                        imageUrl: this.getRoleImage(message.context_data.role),
                        role: message.context_data.role,
                        eliminated: false
                    });
                } else {
                    // Check for elimination events
                    if ((message.type === 'VOTE_RESULT' || message.type === 'MORNING_VICTIM') && 
                        message.context_data && message.context_data.victim) {
                        this.markPlayerAsEliminated(message.context_data.victim);
                    }
                    this.addMessage(message);
                }
            });
            // Handle connection events
            this.socket.on('connect', () => {
                // Connected to WebSocket server
            });
            this.socket.on('disconnect', () => {
                this.addMessage({
                    timestamp: new Date().toISOString(),
                    type: 'system',
                    content: 'Disconnected from game server'
                });
            });
            this.socket.on('connect_error', (error) => {
                this.addMessage({
                    timestamp: new Date().toISOString(),
                    type: 'error',
                    content: 'Failed to connect to game server'
                });
            });
        },
        getPlayerColor(name) {
            const player = this.players.find(p => p.name === name);
            return player ? player.color : '#fff';
        },
        getPlayerRole(name) {
            const player = this.players.find(p => p.name === name);
            return player ? player.role : '';
        },
        getPlayerTextColor(player) {
            const idx = this.players.findIndex(p => p.name === player.name);
            return (idx !== -1) ? this.playerTextColor[idx % this.playerTextColor.length] : '#000';
        },
        getMessageStyle(message) {
            let bgColor = '#fff';
            let color = '#000';
            if (message.type === 'SPEECH') {
                const idx = this.players.findIndex(p => p.name === message.actor_name);
                bgColor = this.getPlayerColor(message.actor_name);
                color = (idx !== -1) ? this.playerTextColor[idx % this.playerTextColor.length] : '#000';
            }
            return { backgroundColor: bgColor, color: color };
        },
        processVoteData(votes) {
            if (!votes || !Array.isArray(votes)) return {};
            
            const voteMap = {};
            votes.forEach(vote => {
                const [voter, accused] = vote;
                if (!voteMap[accused]) {
                    voteMap[accused] = {
                        voters: [],
                        count: 0
                    };
                }
                voteMap[accused].voters.push(voter);
                voteMap[accused].count++;
            });
            
            // Sort by vote count (descending) then by name
            const sortedEntries = Object.entries(voteMap).sort((a, b) => {
                if (b[1].count !== a[1].count) {
                    return b[1].count - a[1].count;
                }
                return a[0].localeCompare(b[0]);
            });
            
            return Object.fromEntries(sortedEntries);
        },
        getVoteCount(votes, target) {
            if (!votes || !Array.isArray(votes) || !target) return 0;
            return votes.filter(vote => vote[1] === target).length;
        },
        handleUserScroll() {
            const container = this.$refs.messageContainer;
            if (!container) return;
            
            // If user scrolls up from bottom, disable auto-scroll
            if (container.scrollTop + container.clientHeight < container.scrollHeight - 10) {
                this.autoScrollEnabled = false;
                this.userHasScrolled = true;
            } else {
                // If user scrolls back to bottom, re-enable auto-scroll
                this.autoScrollEnabled = true;
                this.userHasScrolled = false;
            }
        }
    },
    computed: {
        // No longer need playersFirstRow or playersSecondRow
    },
    mounted() {
        // Fetch log history first
        fetch('/api/logs')
            .then(response => response.json())
            .then(logs => {
                logs.forEach(message => {
                    // Replay ROLE_ASSIGNMENT to rebuild players
                    if (message.type === 'ROLE_ASSIGNMENT') {
                        const playerIndex = this.players.length;
                        this.players.push({
                            name: message.target_name,
                            color: this.playerColors[playerIndex % this.playerColors.length],
                            imageUrl: this.getRoleImage(message.context_data.role),
                            role: message.context_data.role,
                            eliminated: false
                        });
                    } else {
                        // Check for elimination events in historical data
                        if ((message.type === 'VOTE_RESULT' || message.type === 'MORNING_VICTIM') && 
                            message.context_data && message.context_data.victim) {
                            this.markPlayerAsEliminated(message.context_data.victim);
                        }
                        this.addMessage(message);
                    }
                });
                // Now initialize WebSocket connection
                this.initializeSocket();
                // Scroll to bottom after loading logs
                this.scrollToBottom();
                // Add scroll event listener to detect user interaction
                this.$nextTick(() => {
                    const container = this.$refs.messageContainer;
                    if (container) {
                        container.addEventListener('scroll', this.handleUserScroll);
                    }
                });
            });
    },
    beforeDestroy() {
        // Clean up scroll event listener when the component is destroyed
        const container = this.$refs.messageContainer;
        if (container) {
            container.removeEventListener('scroll', this.handleUserScroll);
        }
    }
});
