// frontend/src/components/BillAnalyzer.jsx

import React, { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';
import { Sun, Moon, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import DownloadMenu from './DownloadMenu';
import { useTheme } from '../lib/ThemeProvider';
import AnalysisProgress from './AnalysisProgress';

export default function BillAnalyzer() {
  const [billNumber, setBillNumber] = useState('');
  const [sessionYear, setSessionYear] = useState('2023-2024');
  const [error, setError] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [startTime, setStartTime] = useState(null);
  const [elapsedTime, setElapsedTime] = useState(null);
  const [reportUrl, setReportUrl] = useState(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [stepMessage, setStepMessage] = useState('');
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [stepProgress, setStepProgress] = useState({});
  const [expandedStepId, setExpandedStepId] = useState(null);
  const { theme, toggleTheme } = useTheme();
  const [model, setModel] = useState('gpt-4o-2024-08-06');

  // Socket management
  const [socketConnected, setSocketConnected] = useState(false);
  const socketRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const [currentAnalysisId, setCurrentAnalysisId] = useState(null);

  // Analysis steps definition
  const analysisSteps = [
    { id: 1, name: "Fetching Bill", description: "Retrieving bill text from legislature database" },
    { id: 2, name: "Parsing Text", description: "Extracting sections and digest items" },
    { id: 3, name: "Building Analysis Structure", description: "Creating structured data for analysis" },
    { id: 4, name: "Matching Bill Sections", description: "Connecting digest items to bill sections" },
    { id: 5, name: "Generating Report", description: "Creating the final analysis report" }
  ];

  // Timer for elapsed time
  useEffect(() => {
    let timer;
    if (isProcessing && startTime) {
      timer = setInterval(() => {
        setElapsedTime(formatElapsedTime(startTime, Date.now()));
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [isProcessing, startTime]);

  // Socket connection management
  const connectSocket = () => {
    if (socketRef.current) {
      console.log('Cleaning up existing socket');
      socketRef.current.disconnect();
    }

    console.log('Connecting to socket at:', window.location.origin);
    const socket = io(window.location.origin, {
      path: '/socket.io',
      transports: ['websocket'],
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 20000
    });

    socket.on('connect', () => {
      console.log('Socket connected successfully with ID:', socket.id);
      setSocketConnected(true);
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    });

    socket.on('connection_established', (data) => {
      console.log('Connection established:', data);
    });

    socket.on('disconnect', (reason) => {
      console.log('Socket disconnected:', reason);
      setSocketConnected(false);

      // Only attempt reconnect if we're still processing
      if (isProcessing && !reconnectTimeoutRef.current) {
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log('Attempting to reconnect...');
          connectSocket();
        }, 1000);
      }
    });

    socket.on('analysis_progress', (data) => {
      console.log('Progress update received:', data);

      // Only process updates for current analysis
      if (!currentAnalysisId || data.analysis_id === currentAnalysisId) {
        // Update step information if provided
        if (data.step) {
          setCurrentStep(data.step);
          setStepMessage(data.message || '');
        }

        // Update substep progress if provided
        if (data.current_substep !== undefined) {
          setProgress({
            current: data.current_substep,
            total: data.total_substeps || 0
          });

          // If there's a specific message for this substep
          if (data.message) {
            setStepMessage(data.message);
          }
        }
      }
    });

    socket.on('analysis_complete', (data) => {
      console.log('Analysis complete:', data);
      if (!currentAnalysisId || data.analysis_id === currentAnalysisId) {
        setReportUrl(data.report_url);
        setIsProcessing(false);
        setError(null);
      }
    });

    socket.on('analysis_error', (data) => {
      console.error('Analysis error:', data);
      setError(data.error || 'An error occurred during analysis');
      setIsProcessing(false);
    });

    socket.on('pong', (data) => {
      console.log('Received pong:', data);
    });

    socketRef.current = socket;
  };

  // Connect socket on mount
  useEffect(() => {
    connectSocket();
    return () => {
      console.log('Cleaning up socket connection');
      if (socketRef.current) {
        socketRef.current.disconnect();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, []);

  // Keep connection alive with ping/pong
  useEffect(() => {
    const pingInterval = setInterval(() => {
      if (socketRef.current?.connected && isProcessing) {
        socketRef.current.emit('ping', { timestamp: Date.now() });
      }
    }, 10000);

    return () => clearInterval(pingInterval);
  }, [isProcessing]);

  const onToggleExpand = (stepId) => {
    if (expandedStepId === stepId) {
      setExpandedStepId(null);
    } else {
      setExpandedStepId(stepId);
    }
  };

  const analyzeBill = async () => {
    if (!billNumber) {
      setError('Please enter a bill number');
      return;
    }

    try {
      // Reset state
      setError(null);
      setIsProcessing(true);
      const now = Date.now();
      setStartTime(now);
      setReportUrl(null);
      setCurrentStep(1);
      setStepMessage('Starting bill analysis');
      setProgress({ current: 0, total: 0 });
      setStepProgress({});
      setExpandedStepId(null);

      // Generate unique analysis ID
      const analysisId = `analysis_${now}`;
      setCurrentAnalysisId(analysisId);

      // Ensure socket is connected
      if (!socketRef.current?.connected) {
        console.log('Socket not connected, reconnecting...');
        connectSocket();
        // Wait for connection
        await new Promise((resolve) => {
          const checkConnection = setInterval(() => {
            if (socketRef.current?.connected) {
              clearInterval(checkConnection);
              resolve();
            }
          }, 100);
        });
      }

      console.log('Sending request to analyze bill:', billNumber, 'from session:', sessionYear, 'using model:', model);

      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          billNumber,
          sessionYear,
          model,
          analysisId
        }),
      });

      console.log('Response status:', response.status);
      const data = await response.json();
      console.log('Analysis started successfully:', data);

      if (!response.ok) {
        throw new Error(data.error || 'Failed to start analysis');
      }

    } catch (err) {
      console.error('Error starting analysis:', err);
      setError(err.message || 'Failed to start analysis');
      setIsProcessing(false);
    }
  };

  // Available session years - add new ones at the top as they become available
  const availableSessionYears = [
    '2023-2024',
    '2021-2022',
    '2019-2020',
    '2017-2018'
  ];

  const modelOptions = [
    'gpt-4o-2024-08-06',
    'claude-3-sonnet-20240229'
  ];

  return (
    <div className="container mx-auto px-4 py-8">
      <header className="flex justify-between items-center mb-8">
        <h1 className="text-2xl font-bold">Bill Analyzer</h1>
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700"
        >
          {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </button>
      </header>

      <div className="space-y-4">
        <div className="flex flex-col md:flex-row gap-4">
          <input
            type="text"
            value={billNumber}
            onChange={(e) => setBillNumber(e.target.value.toUpperCase())}
            placeholder="Enter bill number (e.g., AB173)"
            className="flex-1 p-2 border rounded dark:bg-gray-800 dark:border-gray-600"
            disabled={isProcessing}
          />

          <select
            value={sessionYear}
            onChange={(e) => setSessionYear(e.target.value)}
            className="p-2 border rounded dark:bg-gray-800 dark:border-gray-600"
            disabled={isProcessing}
          >
            {availableSessionYears.map(year => (
              <option key={year} value={year}>{year}</option>
            ))}
          </select>

          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="p-2 border rounded dark:bg-gray-800 dark:border-gray-600"
            disabled={isProcessing}
          >
            {modelOptions.map(option => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>

          <button
            onClick={analyzeBill}
            disabled={isProcessing || !billNumber}
            className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:bg-gray-400 disabled:cursor-not-allowed"
          >
            {isProcessing ? 'Analyzing...' : 'Analyze'}
          </button>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {isProcessing && (
          <div className="space-y-4">
            <AnalysisProgress
              currentStep={currentStep}
              stepMessage={stepMessage}
              steps={analysisSteps}
              progress={progress}
              startTime={startTime}
              stepProgress={stepProgress}
              expandedStepId={expandedStepId}
              onToggleExpand={onToggleExpand}
            />
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Time elapsed: {elapsedTime || '0s'}
            </p>
          </div>
        )}

        {reportUrl && (
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-green-500" />
            <span>Analysis complete!</span>
            <DownloadMenu reportUrl={reportUrl} />
          </div>
        )}
      </div>
    </div>
  );
}

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