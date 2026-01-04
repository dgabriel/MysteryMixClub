import apiClient from './client';
import { 
  LoginRequest, 
  LoginResponse, 
  SignupRequest, 
  SignupResponse,
  User 
} from '../types';

export const authApi = {
  /**
   * Sign up a new user
   */
  signup: async (data: SignupRequest): Promise<SignupResponse> => {
    const response = await apiClient.post<SignupResponse>('/auth/signup', data);
    return response.data;
  },

  /**
   * Log in an existing user
   */
  login: async (data: LoginRequest): Promise<LoginResponse> => {
    const response = await apiClient.post<LoginResponse>('/auth/login', data);
    return response.data;
  },

  /**
   * Get current user information
   */
  getCurrentUser: async (): Promise<User> => {
    const response = await apiClient.get<User>('/auth/me');
    return response.data;
  },
};
