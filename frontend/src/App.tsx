socket.on('connect', () => {
    console.log('Socket connected successfully with ID:', socket.id);
    setError(null); // Clear any previous errors on reconnect
  });

  socket.on('disconnect', (reason) => {
    console.log('Socket disconnected:', reason);
    if (reason === 'io server disconnect') {
      // Server initiated disconnect, try to reconnect
      socket.connect();
    }
  });

  socket.on('connect_error', (error) => {
    console.log('Socket connection error:', error);
    setError('Connection lost - analysis may be interrupted');
  });

  socket.io.on('reconnect', (attempt) => {
    console.log('Socket reconnected after', attempt, 'attempts');
    setError(null);
  });