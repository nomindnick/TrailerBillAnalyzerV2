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
  const MAX_RECONNECTS = 10; // Added constant for max reconnect attempts
  const RECONNECT_DELAY = 2000; // Added constant for reconnect delay

  // Ref for reconnection interval
  const reconnectionIntervalRef = useRef(null);
  // Use a ref to keep track of the socket instance for cleanup
  const socketRef = useRef(null);
  let pingInterval; // Declare pingInterval here

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
    const serverUrl = window.location.protocol + '//' + window.location.host;
    console.log('Connecting to socket at:', serverUrl);

    const newSocket = io(serverUrl, {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: MAX_RECONNECTS,
      reconnectionDelay: RECONNECT_DELAY,
      timeout: 120000, // Increased timeout
      pingTimeout: 60000, // Increased ping timeout
      pingInterval: 25000 // More frequent pings
    });

    socketRef.current = newSocket;
    setSocket(newSocket);

    newSocket.on('connect', () => {
      console.log('Socket connected successfully with ID:', newSocket.id);
      setSocketConnected(true);
      setError(null);
      reconnectAttemptsRef.current = 0;
      // Clear any existing reconnection interval
      if (reconnectionIntervalRef.current) {
        clearInterval(reconnectionIntervalRef.current);
        reconnectionIntervalRef.current = null;
      }
    });

    newSocket.on('connect_error', (err) => {
      console.error('Socket connection error:', err);
      setSocketConnected(false);
      reconnectAttemptsRef.current += 1;
      if (reconnectAttemptsRef.current > 3) { // Delay error message
        setError('Error connecting to server. Please reload the page and try again.');
      }
    });

    let isReconnecting = false;
    let reconnectCount = 0;
    newSocket.on('disconnect', (reason) => {
      console.log('Socket disconnected:', reason);
      setSocketConnected(false);

      if (isProcessing && reason !== 'io client disconnect' && !isReconnecting) {
        isReconnecting = true;
        const attemptReconnect = () => {
          if (reconnectCount < MAX_RECONNECTS) {
            console.log(`Attempting to reconnect (${reconnectCount + 1}/${MAX_RECONNECTS})...`);
            reconnectCount++;
            newSocket.connect();

            // Check if connection was successful
            setTimeout(() => {
              if (!newSocket.connected) {
                attemptReconnect();
              }
            }, RECONNECT_DELAY);
          } else {
            isReconnecting = false;
            console.error('Maximum reconnection attempts reached');
            setError('Lost connection to server. Please try again later.');
            setIsProcessing(false);
          }
        };

        attemptReconnect();
      }
    });


    newSocket.on('analysis_progress', (data) => {
      console.log('Progress update received:', data);
      if (data.analysis_id && data.analysis_id !== currentAnalysisRef.current) {
        console.log('Ignoring progress for different analysis:', data.analysis_id);
        return;
      }
      if (error && error.includes('Connection to server lost')) {
        setError(null);
      }
      if (data.step) {
        setCurrentStep(parseInt(data.step, 10));
      }
      if (data.message) {
        setStepMessage(data.message);
      }
      if (data.current_substep !== undefined && data.total_substeps !== undefined) {
        setProgress({
          current: parseInt(data.current_substep, 10),
          total: parseInt(data.total_substeps, 10)
        });
        if (data.step) {
          setStepProgress(prev => ({
            ...prev,
            [data.step]: {
              current: parseInt(data.current_substep, 10),
              total: parseInt(data.total_substeps, 10),
              message: data.message
            }
          }));
        }
      } else if (data.current_substep !== undefined) {
        setProgress(prev => ({ ...prev, current: parseInt(data.current_substep, 10) }));
      }
    });

    newSocket.on('analysis_complete', (data) => {
      console.log('Analysis complete received:', data);
      if (data.analysis_id && data.analysis_id !== currentAnalysisRef.current) {
        console.log('Ignoring completion for different analysis:', data.analysis_id);
        return;
      }
      setIsProcessing(false);
      setCurrentStep(5);
      setStepMessage('Analysis complete!');
      setReportUrl(data.report_url);
      setNotification({
        type: 'success',
        message: 'Analysis complete! You can now view or download the report.'
      });
    });

    newSocket.on('analysis_error', (data) => {
      console.error('Analysis error:', data);
      setIsProcessing(false);
      setError(data.error || 'An unknown error occurred during analysis');
    });

    // Add ping/pong to keep connection alive
    pingInterval = setInterval(() => {
      if (newSocket.connected) {
        newSocket.emit('ping', { timestamp: Date.now() });
      }
    }, 20000);


    return () => {
      console.log('Cleaning up socket connection');
      clearInterval(pingInterval);
      if (socketRef.current) {
        socketRef.current.disconnect();
        socketRef.current = null;
      }
    };
  }, []);


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
    const analysisId = `analysis_${Date.now()}`;
    currentAnalysisRef.current = analysisId;

    try {
      if (!socketConnected) {
        console.log('Socket not connected, attempting to reconnect before analysis');
        if (socketRef.current) {
          socketRef.current.connect();
          await new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
              reject(new Error('Socket reconnection timeout'));
            }, 5000);
            socketRef.current.once('connect', () => {
              clearTimeout(timeout);
              resolve();
            });
          });
        } else {
          throw new Error('Socket connection is not available');
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
          analysisId
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to start analysis');
      }

      console.log('Response status:', response.status);
      const data = await response.json();
      console.log('Analysis started successfully:', data);


      const checkCompletionTimeout = setTimeout(async () => {
        if (isProcessing && currentAnalysisRef.current === analysisId) {
          console.log('Checking for completion status directly...');
          try {
            const checkResponse = await fetch(`/reports/${billNumber}_latest.json`);
            if (checkResponse.ok) {
              const reportData = await checkResponse.json();
              if (reportData && reportData.report_url) {
                console.log('Found completed report via direct check:', reportData);
                setIsProcessing(false);
                setReportUrl(reportData.report_url);
                setCurrentStep(5);
              }
            }
          } catch (err) {
            console.log('Error checking completion status:', err);
          }
        }
      }, 60000); // Check after 60 seconds

      return () => clearTimeout(checkCompletionTimeout);
    } catch (error) {
      console.error('Error starting analysis:', error);
      setError(error.message || 'Failed to start bill analysis');
      setIsProcessing(false);
    }
  };


  useEffect(() => {
    if (socketRef.current && socketConnected && isProcessing) {
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