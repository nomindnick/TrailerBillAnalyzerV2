// Updated BillAnalyzer.jsx component with fixes for WebSocket communication

import React, { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';
import { Sun, Moon, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import DownloadMenu from './DownloadMenu';
import { useTheme } from '../lib/ThemeProvider';
import AnalysisProgress from './AnalysisProgress';

// Helper function to format elapsed time
const formatElapsedTime = (start, now) => {
  const elapsedMs = now - start;
  const seconds = Math.floor(elapsedMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
  } else if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`;
  } else {
    return `${seconds}s`;
  }
};

const BillAnalyzer = () => {
  const [billNumber, setBillNumber] = useState('');
  const [sessionYear, setSessionYear] = useState('2023-2024'); // Default to current session
  const [selectedModel, setSelectedModel] = useState('gpt-4o-2024-08-06'); // Default to GPT-4o
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [stepMessage, setStepMessage] = useState('');
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [stepProgress, setStepProgress] = useState({});
  const [error, setError] = useState(null);
  const [reportUrl, setReportUrl] = useState(null);
  const [socket, setSocket] = useState(null);
  const [notification, setNotification] = useState(null);
  const [startTime, setStartTime] = useState(null);
  const [expandedStepId, setExpandedStepId] = useState(null);

  // Use a ref to track the current analysis ID
  const currentAnalysisRef = useRef(null);

  // New state for socket connection status
  const [socketConnected, setSocketConnected] = useState(false);
  const reconnectAttemptsRef = useRef(0);
  const maxReconnectAttempts = 10;

  // Use a ref to keep track of the socket instance for cleanup
  const socketRef = useRef(null);

  // Available session years - add new ones at the top as they become available
  const availableSessionYears = [
    "2025-2026",
    "2023-2024",
    "2021-2022",
    "2019-2020",
    "2017-2018",
    "2015-2016"
  ];

  // Available AI models - add new models here as they become available
  const availableModels = [
    { id: "gpt-4o-2024-08-06", name: "GPT-4o (Default)" },
    { id: "o3-mini-2025-01-31", name: "o3-mini (Reasoning)" },
    { id: "claude-3-7-sonnet-20250219", name: "Claude 3.7 (Deep Thinking)" }
  ];

  // Use the global theme from ThemeProvider
  const { theme, toggleTheme } = useTheme();

  const steps = [
    { id: 1, name: 'Fetching Bill Text', description: 'Retrieving bill content from legislature website' },
    { id: 2, name: 'Initial Parsing', description: 'Breaking down bill into components' },
    { id: 3, name: 'Building Analysis Structure', description: 'Creating framework for analysis' },
    { id: 4, name: 'AI Analysis', description: 'Analyzing changes and impacts' },
    { id: 5, name: 'Report Generation', description: 'Creating final report' }
  ];

  // Establish socket connection immediately on component mount
  useEffect(() => {
    // Function to create and connect socket
    const connectSocket = () => {
      // Create socket URL based on current location
      const protocol = window.location.protocol;
      const host = window.location.host;
      const socketUrl = `${protocol}//${host}`;

      console.log('Connecting to socket at:', socketUrl);

      // Close any existing socket connection
      if (socketRef.current) {
        socketRef.current.disconnect();
      }

      // Create new socket connection
      const newSocket = io(socketUrl, {
        path: '/socket.io',
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: maxReconnectAttempts,
        reconnectionDelay: 1000,
        timeout: 20000,
      });

      // Store socket reference for cleanup
      socketRef.current = newSocket;
      setSocket(newSocket);

      // Connection event handlers
      newSocket.on('connect', () => {
        console.log('Socket connected successfully with ID:', newSocket.id);
        setSocketConnected(true);
        setError(null);
        reconnectAttemptsRef.current = 0;
      });

      newSocket.on('connect_error', (err) => {
        console.error('Socket connection error:', err);
        setSocketConnected(false);
        reconnectAttemptsRef.current += 1;

        if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
          setError('Failed to connect to analysis server. Please try again later.');
        } else if (isProcessing) {
          setError(`Connection to server lost. Attempting to reconnect... (${reconnectAttemptsRef.current}/${maxReconnectAttempts})`);
        }
      });

      newSocket.on('disconnect', (reason) => {
        console.log('Socket disconnected:', reason);
        setSocketConnected(false);

        if (isProcessing) {
          setError('Connection to analysis server lost. The analysis may still be running.');

          // Try to reconnect automatically
          setTimeout(() => {
            if (isProcessing) {
              console.log('Attempting to reconnect socket...');
              newSocket.connect();
            }
          }, 1000);
        }
      });

      // Set up event listeners for analysis progress
      newSocket.on('analysis_progress', (data) => {
        console.log('Progress update received:', data);

        // Only process events for the current analysis
        if (!currentAnalysisRef.current || data.analysis_id === currentAnalysisRef.current) {
          // Clear any connection errors since we're receiving events
          if (error && error.includes('Connection to server lost')) {
            setError(null);
          }

          // Update step if provided
          if (data.step !== undefined) {
            setCurrentStep(data.step);
          }

          // Update message if provided
          if (data.message) {
            setStepMessage(data.message);
          }

          // Handle substeps tracking
          if (data.current_substep !== undefined) {
            setProgress(prev => ({
              current: data.current_substep,
              total: data.total_substeps || prev.total
            }));
          }

          // Update step-specific progress
          if (data.step && data.step_progress !== undefined) {
            setStepProgress(prev => ({
              ...prev,
              [data.step]: data.step_progress
            }));
          }
        }
      });

      // Handle analysis completion
      newSocket.on('analysis_complete', (data) => {
        console.log('Analysis complete received:', data);

        // Only process events for the current analysis
        if (!currentAnalysisRef.current || data.analysis_id === currentAnalysisRef.current) {
          setIsProcessing(false);
          currentAnalysisRef.current = null;

          if (data && data.report_url) {
            setReportUrl(data.report_url);

            setNotification({
              type: 'success',
              message: 'Analysis completed successfully!'
            });

            // Clear notification after 5 seconds
            setTimeout(() => setNotification(null), 5000);
          } else {
            console.error('Missing report URL in completion event:', data);
            setError('Analysis completed but report URL is missing');
          }
        }
      });

      // Handle analysis errors
      newSocket.on('analysis_error', (data) => {
        console.error('Analysis error received:', data);

        if (!currentAnalysisRef.current || data.analysis_id === currentAnalysisRef.current) {
          setError(data.error || 'Unknown error occurred during analysis');
          setIsProcessing(false);
          currentAnalysisRef.current = null;
        }
      });
    };

    // Connect socket
    connectSocket();

    // Cleanup on unmount
    return () => {
      console.log('Cleaning up socket connection');
      if (socketRef.current) {
        socketRef.current.disconnect();
        socketRef.current = null;
      }
    };
  }, []); // Empty dependency array means this runs once on component mount

  // Create a periodic ping to keep the socket connection alive
  useEffect(() => {
    let pingInterval;

    if (socketRef.current && socketConnected && isProcessing) {
      // Send a ping every 5 seconds to keep the connection alive
      pingInterval = setInterval(() => {
        try {
          socketRef.current.emit('ping', { timestamp: Date.now() });
          console.log('Ping sent to keep connection alive');
        } catch (err) {
          console.error('Error sending ping:', err);
        }
      }, 5000);
    }

    return () => {
      if (pingInterval) {
        clearInterval(pingInterval);
      }
    };
  }, [socketConnected, isProcessing]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsProcessing(true);
    setCurrentStep(1);
    setError(null);
    setReportUrl(null);
    setNotification(null);
    setStartTime(new Date());
    setStepProgress({});
    setExpandedStepId(null);

    // Generate a unique ID for this analysis
    const analysisId = `analysis_${Date.now()}`;
    currentAnalysisRef.current = analysisId;

    try {
      // Ensure socket is connected before proceeding
      if (!socketConnected) {
        console.log('Socket not connected, attempting to connect now...');
        // If socket isn't connected, try to reconnect
        if (socketRef.current) {
          socketRef.current.connect();
        } else {
          // If no socket exists, we have a bigger problem
          throw new Error('Socket connection not available. Please refresh the page and try again.');
        }

        // Wait a moment for connection to establish
        await new Promise(resolve => setTimeout(resolve, 1000));

        if (!socketConnected) {
          throw new Error('Cannot connect to analysis server. Please refresh and try again.');
        }
      }

      console.log('Sending request to analyze bill:', billNumber, 'from session:', sessionYear, 'using model:', selectedModel);
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          billNumber,
          sessionYear,
          model: selectedModel,
          analysisId // Include the analysis ID in the request
        })
      });

      console.log('Response status:', response.status);

      if (!response.ok) {
        const data = await response.json();
        console.error('Error response:', data);
        throw new Error(data.error || 'Failed to start analysis');
      }

      // Analysis started successfully
      const data = await response.json();
      console.log('Analysis started successfully:', data);

      // Force a check of socket connection after starting analysis
      if (!socketConnected && socketRef.current) {
        console.log('Reconnecting socket after analysis start...');
        socketRef.current.connect();
      }
    } catch (err) {
      console.error('Error starting analysis:', err);
      setError(err.message || 'Failed to connect to server');
      setIsProcessing(false);
      currentAnalysisRef.current = null;
    }
  };

  return (
    <div className="min-h-screen p-8 bg-background text-foreground transition-colors duration-200">
      <div className="max-w-4xl mx-auto">
        {/* Header with theme toggle button */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
              Trailer Bill Analyzer
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Analyze California trailer bills for local agency impacts
            </p>
          </div>
          <button
            onClick={toggleTheme}
            className={`p-2 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${
              theme === 'dark' ? 'text-gray-200' : 'text-gray-700'
            }`}
            aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? <Sun size={24} /> : <Moon size={24} />}
          </button>
        </div>

        {/* Connection status indicator - more prominent now */}
        {!socketConnected && (
          <div className="mb-4 p-3 bg-yellow-100 dark:bg-yellow-900 border border-yellow-200 dark:border-yellow-800 rounded-lg flex items-center text-yellow-800 dark:text-yellow-200">
            <AlertTriangle className="h-5 w-5 mr-2" />
            <span>
              <strong>WebSocket disconnected:</strong> Waiting for connection to server...
              {isProcessing && " This will affect progress updates."}
            </span>
          </div>
        )}

        {/* Success notification */}
        {notification && notification.type === 'success' && (
          <div className="mb-6 p-4 bg-green-100 dark:bg-green-900 border border-green-200 dark:border-green-800 rounded-lg flex items-center text-green-800 dark:text-green-200 animate-fade-in">
            <CheckCircle2 className="h-5 w-5 mr-2" />
            <span>{notification.message}</span>
          </div>
        )}

        {/* Error alert */}
        {error && (
          <Alert variant="destructive" className="mb-6">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Input form */}
        <div className="mb-8 bg-white dark:bg-gray-800 rounded-lg p-6 shadow-lg transition-all">
          <form onSubmit={handleSubmit}>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
              <div className="sm:col-span-2">
                <label htmlFor="billNumber" className="block text-sm font-medium mb-1 text-gray-700 dark:text-gray-300">
                  Bill Number
                </label>
                <input
                  id="billNumber"
                  type="text"
                  value={billNumber}
                  onChange={(e) => setBillNumber(e.target.value)}
                  placeholder="e.g., AB173"
                  className="w-full p-3 border rounded-lg text-gray-900 dark:text-gray-100 dark:bg-gray-700 dark:border-gray-600 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
                  disabled={isProcessing}
                />
              </div>
              <div>
                <label htmlFor="sessionYear" className="block text-sm font-medium mb-1 text-gray-700 dark:text-gray-300">
                  Session Year
                </label>
                <select
                  id="sessionYear"
                  value={sessionYear}
                  onChange={(e) => setSessionYear(e.target.value)}
                  className="w-full p-3 border rounded-lg text-gray-900 dark:text-gray-100 dark:bg-gray-700 dark:border-gray-600 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
                  disabled={isProcessing}
                >
                  {availableSessionYears.map((year) => (
                    <option key={year} value={year}>
                      {year}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mb-4">
              <label htmlFor="aiModel" className="block text-sm font-medium mb-1 text-gray-700 dark:text-gray-300">
                AI Model
              </label>
              <select
                id="aiModel"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full p-3 border rounded-lg text-gray-900 dark:text-gray-100 dark:bg-gray-700 dark:border-gray-600 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
                disabled={isProcessing}
              >
                {availableModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Select different models to compare analysis quality and performance
              </p>
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={isProcessing || !billNumber}
                className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-200 shadow-md hover:shadow-lg"
              >
                {isProcessing ? 'Analyzing...' : 'Analyze Bill'}
              </button>
            </div>
          </form>
        </div>

        {/* Progress display */}
        {isProcessing && (
          <AnalysisProgress 
            currentStep={currentStep}
            stepMessage={stepMessage}
            steps={steps}
            progress={progress}
            startTime={startTime}
            stepProgress={stepProgress}
            expandedStepId={expandedStepId}
            onToggleExpand={(stepId) => setExpandedStepId(stepId === expandedStepId ? null : stepId)}
          />
        )}

        {/* Report download section when analysis completes */}
        {reportUrl && (
          <div className="mt-6 p-6 bg-white dark:bg-gray-800 rounded-lg shadow-lg flex flex-col items-center text-center animate-fade-in">
            <h3 className="text-xl font-semibold mb-4">Analysis Complete!</h3>
            <p className="mb-6 text-gray-600 dark:text-gray-300">
              Your bill analysis is ready for review and download.
              {startTime && (
                <span className="block mt-2 text-sm font-medium text-blue-600 dark:text-blue-400">
                  Total time: {formatElapsedTime(startTime, new Date())}
                </span>
              )}
            </p>
            <DownloadMenu reportUrl={reportUrl} />
          </div>
        )}
      </div>
    </div>
  );
};

export default BillAnalyzer;